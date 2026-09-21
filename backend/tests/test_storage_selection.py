"""Which storage provider gets used, and when.

NOTE: unlike the rest of this phase, these tests were written after the function they
cover -- it was added while debugging a 500 from the live API. They are kept because
the behaviour matters, but they did not drive the design.

The rule they lock in: local development falls back to the in-memory provider so the
app is runnable without bucket credentials, and production refuses to start without
them rather than failing at the first upload with an opaque credentials error.
"""

import pytest

from app.core.config import Settings, get_settings
from app.storage.base import get_storage_provider
from app.storage.fake import FakeStorageProvider

BASE_ENV = {
    "database_url": "postgresql://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
    "jwt_secret": "x" * 32,
    # Pinned rather than omitted. `Settings` reads the .env file, so leaving these
    # out makes the test describe whatever the developer's environment happens to
    # contain -- which is how it passed for as long as nobody had bucket
    # credentials configured, and broke the moment somebody did.
    "r2_endpoint_url": None,
    "r2_access_key_id": None,
    "r2_secret_access_key": None,
}


@pytest.fixture(autouse=True)
def _clear_caches():
    """Both the settings and the provider are cached per process."""
    get_settings.cache_clear()
    get_storage_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_storage_provider.cache_clear()


def _settings(**overrides: object) -> Settings:
    return Settings(**{**BASE_ENV, **overrides})  # type: ignore[arg-type]


def test_local_without_credentials_falls_back_to_the_in_memory_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requiring bucket credentials to run the app locally is how a project stops
    being runnable by anyone who did not set it up."""
    monkeypatch.setattr("app.storage.base.get_settings", lambda: _settings(environment="local"))

    assert isinstance(get_storage_provider(), FakeStorageProvider)


def test_production_without_credentials_refuses_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Silently discarding a caregiver's recording is the worst possible outcome."""
    monkeypatch.setattr(
        "app.storage.base.get_settings", lambda: _settings(environment="production")
    )

    with pytest.raises(RuntimeError, match="not configured"):
        get_storage_provider()


def test_partial_credentials_are_treated_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An endpoint with no key is a half-finished deployment, not a valid setup."""
    monkeypatch.setattr(
        "app.storage.base.get_settings",
        lambda: _settings(
            environment="production", r2_endpoint_url="https://example.r2.cloudflarestorage.com"
        ),
    )

    with pytest.raises(RuntimeError, match="not configured"):
        get_storage_provider()


def test_full_credentials_select_the_s3_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.storage.base.get_settings",
        lambda: _settings(
            environment="production",
            r2_endpoint_url="https://example.r2.cloudflarestorage.com",
            r2_access_key_id="key",
            r2_secret_access_key="secret",
        ),
    )

    provider = get_storage_provider()
    assert type(provider).__name__ == "S3StorageProvider"
