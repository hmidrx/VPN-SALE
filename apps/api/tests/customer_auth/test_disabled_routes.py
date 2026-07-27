from collections.abc import Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.customer_auth import routes
from platform_api.database import get_db_session
from platform_api.identity.models import IdentityBase, UserModel
from platform_api.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/register", "/password-login"])
@pytest.mark.parametrize("proxy_headers", [{}, {"x-forwarded-for": "203.0.113.9"}])
@pytest.mark.parametrize("payload", [{"username": "valid-user", "password": "not-used"}, {}])
async def test_disabled_password_routes_are_absent_before_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    proxy_headers: dict[str, str],
    payload: dict[str, str],
) -> None:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(UserModel))
    calls: list[str] = []

    def forbidden_db() -> Generator[Session, None, None]:
        calls.append("database")
        raise AssertionError("disabled route opened a database session")
        yield

    def forbidden_limiter() -> routes.RateLimiter:
        calls.append("redis-or-limiter")
        raise AssertionError("disabled route constructed a limiter")

    def forbidden_service(*args: object) -> routes.CustomerAuthService:
        calls.append("password-service")
        raise AssertionError("disabled route constructed password services")

    monkeypatch.setattr(routes, "_svc", forbidden_service)
    app: FastAPI = create_app(
        Settings(
            environment="test",
            public_account_registration_enabled=False,
            password_account_login_enabled=False,
        )
    )
    app.dependency_overrides[get_db_session] = forbidden_db
    app.dependency_overrides[routes.get_customer_rate_limiter] = forbidden_limiter
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1/customer/auth"
    ) as client:
        response = await client.post(path, json=payload, headers=proxy_headers)

    with Session(engine) as session:
        after = session.scalar(select(func.count()).select_from(UserModel))
    assert response.status_code == 404
    assert "set-cookie" not in response.headers
    assert calls == []
    assert before == after == 0


@pytest.mark.asyncio
async def test_existing_database_backed_auth_route_reaches_authorization_logic() -> None:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)

    def database() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app = create_app(Settings(environment="test"))
    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/customer/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/telegram-link/challenge",
        "/telegram-link/complete",
        "/telegram-link/unlink",
        "/account-credentials/enroll",
    ],
)
async def test_disabled_unified_account_routes_are_absent_before_all_dependencies(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    calls: list[str] = []

    def forbidden_db() -> Generator[Session, None, None]:
        calls.append("database")
        raise AssertionError("disabled route opened the database")
        yield

    def forbidden_limiter() -> routes.RateLimiter:
        calls.append("limiter-or-redis")
        raise AssertionError("disabled route constructed its limiter")

    def forbidden_service(*args: object) -> routes.CustomerAuthService:
        calls.append("hasher-or-telegram-verifier")
        raise AssertionError("disabled route constructed security services")

    monkeypatch.setattr(routes, "_svc", forbidden_service)
    app = create_app(Settings(environment="test", telegram_account_linking_enabled=False))
    app.dependency_overrides[get_db_session] = forbidden_db
    app.dependency_overrides[routes.get_customer_rate_limiter] = forbidden_limiter
    assert path not in app.openapi()["paths"]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api/v1/customer/auth"
    ) as client:
        response = await client.post(path, json={"password": "not-used"})
        capabilities = await client.get("/capabilities")
    assert response.status_code == 404
    assert "set-cookie" not in response.headers
    assert calls == []
    assert capabilities.json()["telegram_linking"] is False
    assert capabilities.json()["web_credential_enrollment"] is False
