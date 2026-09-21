"""In-memory storage provider for tests.

Records what it was asked to do so tests can assert on the negotiation without a
bucket. Deliberately not a mock: it behaves like storage, so a test that passes here
is exercising real logic rather than an expectation about a call.
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.storage.base import CompletedPart, ObjectNotFoundError, PresignedPart


@dataclass
class FakeStorageProvider:
    # Bytes a test has placed in the bucket. Uploads are presigned and go
    # straight to storage, so nothing populates this by itself -- a test that wants
    # the pipeline to find audio puts it here.
    objects: dict[str, bytes] = field(default_factory=dict)
    uploads: dict[str, str] = field(default_factory=dict)
    completed: dict[str, list[CompletedPart]] = field(default_factory=dict)
    aborted: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    _counter: int = 0

    async def presigned_put(self, key: str, content_type: str) -> str:
        return f"https://storage.test/{key}?signature=fake&type={content_type}"

    async def create_multipart(self, key: str, content_type: str) -> str:
        self._counter += 1
        upload_id = f"upload-{self._counter}"
        self.uploads[key] = upload_id
        return upload_id

    async def presigned_parts(
        self, key: str, upload_id: str, part_numbers: list[int]
    ) -> list[PresignedPart]:
        return [
            PresignedPart(
                part_number=number,
                url=f"https://storage.test/{key}?uploadId={upload_id}&partNumber={number}",
            )
            for number in part_numbers
        ]

    async def complete_multipart(
        self, key: str, upload_id: str, parts: list[CompletedPart]
    ) -> None:
        self.completed[key] = parts

    async def abort_multipart(self, key: str, upload_id: str) -> None:
        self.aborted.append(key)

    async def delete(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def download(self, key: str, destination: Path) -> None:
        if key not in self.objects:
            raise ObjectNotFoundError(key)
        destination.write_bytes(self.objects[key])
