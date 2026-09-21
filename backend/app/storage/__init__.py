"""Object storage, behind a protocol.

Follows the same shape as the LLM and transcription providers: a Protocol, a live
implementation, and a fake used by tests so nothing here touches a network or a
bucket during a test run.
"""

from app.storage.base import (
    CompletedPart,
    PresignedPart,
    StorageProvider,
    get_storage_provider,
)
from app.storage.fake import FakeStorageProvider

__all__ = [
    "CompletedPart",
    "FakeStorageProvider",
    "PresignedPart",
    "StorageProvider",
    "get_storage_provider",
]
