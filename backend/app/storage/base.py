"""Storage provider protocol.

S3-compatible, because the production bucket is Cloudflare R2 and the same interface
serves MinIO locally or S3 itself if the deployment moves. No vendor type escapes this
package -- services see only the dataclasses defined here.
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PresignedPart:
    part_number: int
    url: str


@dataclass(frozen=True, slots=True)
class CompletedPart:
    part_number: int
    etag: str


class StorageProvider(Protocol):
    """Presigned-URL operations.

    Bytes never pass through the API. The client uploads straight to the bucket with
    a short-lived URL, which keeps a 200MB recording off the application's memory and
    bandwidth entirely.
    """

    async def presigned_put(self, key: str, content_type: str) -> str: ...

    async def create_multipart(self, key: str, content_type: str) -> str: ...

    async def presigned_parts(
        self, key: str, upload_id: str, part_numbers: list[int]
    ) -> list[PresignedPart]: ...

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[CompletedPart]
    ) -> None: ...

    async def abort_multipart(self, key: str, upload_id: str) -> None: ...

    async def delete(self, key: str) -> None: ...


@lru_cache
def get_storage_provider() -> StorageProvider:
    """FastAPI dependency resolving to the configured storage backend.

    Local development has no bucket and no credentials, so it falls back to the
    in-memory provider with a warning. Production does not: unconfigured storage
    there is a deployment error, and failing at the first upload with an opaque
    credentials exception is far worse than refusing to start.

    The fallback exists because the alternative -- every developer needing R2 keys
    before they can run the app -- is how a project stops being runnable.
    """
    settings = get_settings()
    configured = bool(
        settings.r2_endpoint_url and settings.r2_access_key_id and settings.r2_secret_access_key
    )

    if not configured:
        if settings.is_production:
            raise RuntimeError(
                "object storage is not configured; set R2_ENDPOINT_URL, "
                "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY"
            )
        logger.warning(
            "object storage is not configured; using the in-memory provider. "
            "Uploads will be accepted and discarded.",
            extra={"environment": settings.environment},
        )
        from app.storage.fake import FakeStorageProvider

        return FakeStorageProvider()

    from app.storage.s3 import S3StorageProvider

    return S3StorageProvider()
