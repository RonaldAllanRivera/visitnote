"""Audio upload negotiation.

Bytes never pass through the API. The client is handed short-lived presigned URLs and
uploads straight to the bucket, which keeps a 200MB recording off the application's
memory and bandwidth entirely.
"""

import math
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import Visit
from app.models.enums import VisitStatus
from app.schemas.upload import (
    ALLOWED_CONTENT_TYPES,
    MULTIPART_THRESHOLD_BYTES,
    PART_SIZE_BYTES,
    PartsResponse,
    PartUrl,
    UploadBegin,
    UploadComplete,
    UploadTicket,
)
from app.storage import CompletedPart, StorageProvider


class UnsupportedContentTypeError(Exception):
    """Not an audio type this system accepts."""


class UploadStateError(Exception):
    """The requested operation does not match the visit's upload state."""


def audio_key(visit: Visit) -> str:
    """Where a visit's audio lives.

    Prefixed by user so a bucket listing groups by tenant, which makes a targeted
    deletion for a data-removal request straightforward.
    """
    return f"audio/{visit.user_id}/{visit.id}"


@dataclass(slots=True)
class UploadService:
    session: AsyncSession
    storage: StorageProvider

    async def begin(self, visit: Visit, payload: UploadBegin) -> UploadTicket:
        if payload.content_type.lower() not in ALLOWED_CONTENT_TYPES:
            raise UnsupportedContentTypeError(payload.content_type)

        key = audio_key(visit)

        if payload.size_bytes <= MULTIPART_THRESHOLD_BYTES:
            url = await self.storage.presigned_put(key, payload.content_type)
            # upload_id stays null: that is how `complete` knows this was a single PUT
            # rather than a multipart assembly.
            visit.upload_id = None
            visit.upload_started_at = utcnow()
            await self.session.commit()
            return UploadTicket(mode="single", url=url, parts=[])

        upload_id = await self.storage.create_multipart(key, payload.content_type)
        part_count = math.ceil(payload.size_bytes / PART_SIZE_BYTES)
        parts = await self.storage.presigned_parts(
            key, upload_id, list(range(1, part_count + 1))
        )

        # Persisted so a client that loses its state mid-upload can resume rather than
        # restart -- and so an abandoned upload can be found and aborted later.
        visit.upload_id = upload_id
        visit.upload_started_at = utcnow()
        await self.session.commit()

        return UploadTicket(
            mode="multipart",
            upload_id=upload_id,
            part_size_bytes=PART_SIZE_BYTES,
            parts=[PartUrl(part_number=p.part_number, url=p.url) for p in parts],
        )

    async def reissue_parts(self, visit: Visit, part_numbers: list[int]) -> PartsResponse:
        """Fresh URLs for an upload already in progress.

        Presigned URLs expire, and a field upload can outlive one. Reissuing against
        the stored upload id continues the same upload; starting a new one would
        orphan every part already transferred.
        """
        if visit.upload_id is None:
            raise UploadStateError("no multipart upload in progress")

        parts = await self.storage.presigned_parts(
            audio_key(visit), visit.upload_id, part_numbers
        )
        return PartsResponse(
            upload_id=visit.upload_id,
            parts=[PartUrl(part_number=p.part_number, url=p.url) for p in parts],
        )

    async def complete(self, visit: Visit, payload: UploadComplete) -> Visit:
        key = audio_key(visit)

        if visit.audio_key is not None:
            raise UploadStateError("upload already completed")
        if visit.upload_started_at is None:
            raise UploadStateError("no upload in progress")

        if visit.upload_id is not None:
            if not payload.parts:
                # S3 assembles the object from the part ETags. Without them the upload
                # stays incomplete: invisible in a listing, but still billed.
                raise UploadStateError("multipart completion requires the part list")

            await self.storage.complete_multipart(
                key,
                visit.upload_id,
                [CompletedPart(part_number=p.part_number, etag=p.etag) for p in payload.parts],
            )
            visit.upload_id = None

        visit.upload_started_at = None
        visit.audio_key = key
        visit.status = VisitStatus.UPLOADED
        await self.session.commit()
        await self.session.refresh(visit)
        return visit
