"""Presigned URLs against a separately reachable endpoint.

The bucket the API talks to and the bucket the browser talks to are not always the
same address. In local development the API reaches MinIO at `minio:9000` on the
compose network while the browser can only reach `localhost:9000`; in production a
bucket often has a public domain distinct from its API endpoint.

A presigned URL is signed over the host it will be sent to, so signing with the
internal address produces a URL the browser cannot use, and re-writing the host
afterwards would invalidate the signature. The endpoint has to differ at signing
time, which is what these tests pin down.
"""

from urllib.parse import urlparse

import pytest

from app.core.config import get_settings
from app.storage.s3 import S3StorageProvider


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "r2_endpoint_url", "http://minio:9000")
    # Cleared explicitly: the developer's .env sets this for local MinIO, and a test
    # that inherits it is describing the machine it runs on rather than the code.
    monkeypatch.setattr(settings, "r2_public_endpoint_url", None)
    monkeypatch.setattr(settings, "r2_access_key_id", "test-key")
    monkeypatch.setattr(settings, "r2_secret_access_key", "test-secret")
    monkeypatch.setattr(settings, "r2_bucket", "visitnote-test")


async def test_a_presigned_url_uses_the_internal_endpoint_by_default(
    configured: None,
) -> None:
    """With one address, both the API and the client use it; nothing special happens."""
    url = await S3StorageProvider().presigned_put("audio/visit-1", "audio/webm")

    assert urlparse(url).netloc == "minio:9000"


async def test_a_presigned_url_uses_the_public_endpoint_when_one_is_configured(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "r2_public_endpoint_url", "http://localhost:9000")

    url = await S3StorageProvider().presigned_put("audio/visit-1", "audio/webm")

    assert urlparse(url).netloc == "localhost:9000"


async def test_the_signature_is_produced_for_the_public_host(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rewriting the host after signing would produce a URL the bucket rejects."""
    monkeypatch.setattr(get_settings(), "r2_public_endpoint_url", "http://localhost:9000")

    url = await S3StorageProvider().presigned_put("audio/visit-1", "audio/webm")

    assert "X-Amz-Signature=" in url
    assert "minio" not in url


async def test_multipart_part_urls_also_use_the_public_endpoint(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A large upload is the case that matters most: it is every part, not one URL."""
    monkeypatch.setattr(get_settings(), "r2_public_endpoint_url", "http://localhost:9000")

    parts = await S3StorageProvider().presigned_parts("audio/visit-1", "upload-1", [1, 2])

    assert [urlparse(part.url).netloc for part in parts] == ["localhost:9000", "localhost:9000"]
