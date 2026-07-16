import pytest
from httpx import ASGITransport, AsyncClient

from platform_api import main


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_version_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    assert body["environment"]


@pytest.mark.asyncio
async def test_metrics_endpoint_does_not_expose_sensitive_values() -> None:
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "vpnsale_api_info" in body
    assert "password" not in body.lower()
    assert "token" not in body.lower()
    assert "secret" not in body.lower()


@pytest.mark.asyncio
async def test_ready_endpoint_reports_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    async def healthy() -> bool:
        return True

    monkeypatch.setattr(main, "check_database", healthy)
    monkeypatch.setattr(main, "check_redis", healthy)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": True, "redis": True}}


@pytest.mark.asyncio
async def test_ready_endpoint_reports_dependency_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def healthy() -> bool:
        return True

    async def unhealthy() -> bool:
        return False

    monkeypatch.setattr(main, "check_database", unhealthy)
    monkeypatch.setattr(main, "check_redis", healthy)
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": False, "redis": True}}
