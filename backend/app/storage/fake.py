"""In-memory storage provider for tests.

Records what it was asked to do so tests can assert on the negotiation without a
bucket. Deliberately not a mock: it behaves like storage, so a test that passes here
is exercising real logic rather than an expectation about a call.
"""

from dataclasses import dataclass, field

from app.storage.base import CompletedPart, PresignedPart


@dataclass
class FakeStorageProvider:
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
