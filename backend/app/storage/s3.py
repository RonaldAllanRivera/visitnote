"""S3-compatible storage (Cloudflare R2 in production).

R2 speaks the S3 API, so this works unchanged against MinIO locally or S3 itself.
That portability is deliberate: the deployment target is meant to be replaceable.
"""

from types import TracebackType
from typing import Any

import aioboto3
from botocore.config import Config

from app.core.config import get_settings
from app.storage.base import CompletedPart, PresignedPart


class S3StorageProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.r2_bucket
        self._expiry = settings.presigned_url_ttl_seconds
        self._session = aioboto3.Session(
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        self._endpoint = settings.r2_endpoint_url
        # SigV4 explicitly: R2 rejects the older signature versions some botocore
        # defaults still negotiate.
        self._config = Config(signature_version="s3v4")

    def _client(self) -> Any:
        """aioboto3 ships no type information, so the untyped seam is confined to
        this one method. Everything this class returns is a typed dataclass."""
        return self._session.client(
            "s3", endpoint_url=self._endpoint, config=self._config
        )

    async def presigned_put(self, key: str, content_type: str) -> str:
        async with self._client() as s3:
            url = await s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=self._expiry,
            )
        # Coerced at the boundary: nothing outside this module ever sees an Any.
        return str(url)

    async def create_multipart(self, key: str, content_type: str) -> str:
        async with self._client() as s3:
            response = await s3.create_multipart_upload(
                Bucket=self._bucket, Key=key, ContentType=content_type
            )
            return str(response["UploadId"])

    async def presigned_parts(
        self, key: str, upload_id: str, part_numbers: list[int]
    ) -> list[PresignedPart]:
        async with self._client() as s3:
            return [
                PresignedPart(
                    part_number=number,
                    url=str(
                        await s3.generate_presigned_url(
                            "upload_part",
                            Params={
                                "Bucket": self._bucket,
                                "Key": key,
                                "UploadId": upload_id,
                                "PartNumber": number,
                            },
                            ExpiresIn=self._expiry,
                        )
                    ),
                )
                for number in part_numbers
            ]

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[CompletedPart]
    ) -> None:
        async with self._client() as s3:
            await s3.complete_multipart_upload(
                Bucket=self._bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={
                    # S3 requires ascending part numbers; an out-of-order list is
                    # rejected with an unhelpful error.
                    "Parts": [
                        {"PartNumber": part.part_number, "ETag": part.etag}
                        for part in sorted(parts, key=lambda p: p.part_number)
                    ]
                },
            )

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        """Abandon an upload so its parts stop accruing storage charges.

        An incomplete multipart upload is invisible in a normal bucket listing but is
        still billed, which is how a storage bill grows without any visible objects.
        """
        async with self._client() as s3:
            await s3.abort_multipart_upload(Bucket=self._bucket, Key=key, UploadId=upload_id)

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def __aenter__(self) -> "S3StorageProvider":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None
