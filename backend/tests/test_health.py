"""Health endpoint contract.

The deploy pipeline polls this endpoint to decide whether a release succeeded, so its
behaviour under a failed dependency is part of the contract, not an implementation
detail.
"""

from httpx import AsyncClient


async def test_healthz_reports_ok_when_dependencies_are_up(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"]["status"] == "ok"
    assert body["dependencies"]["redis"]["status"] == "ok"


async def test_healthz_reports_latency_per_dependency(client: AsyncClient) -> None:
    body = (await client.get("/healthz")).json()
    for name in ("database", "redis"):
        assert body["dependencies"][name]["latency_ms"] >= 0, name


async def test_openapi_schema_is_served_under_the_version_prefix(
    client: AsyncClient,
) -> None:
    """Clients generate their types from this URL; moving it breaks both of them."""
    response = await client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "VisitNote AI"


async def test_forged_host_header_is_rejected(client: AsyncClient) -> None:
    """TrustedHostMiddleware runs before anything else looks at the request.

    Host header injection is how an attacker turns a password-reset link into a
    link pointing at their own domain. This asserts the middleware is actually
    installed, not merely configured.
    """
    response = await client.get("/healthz", headers={"Host": "attacker.example"})
    assert response.status_code == 400
