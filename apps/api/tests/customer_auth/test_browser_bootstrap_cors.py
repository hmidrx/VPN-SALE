from collections.abc import Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from platform_api.config import Settings
from platform_api.customer_auth import routes
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.database import get_db_session
from platform_api.identity.models import IdentityBase
from platform_api.identity.rbac_seed import seed_initial_rbac
from platform_api.main import create_app

CUSTOMER_ORIGIN = "https://app.dr-ping.com"
ADMIN_ORIGIN = "https://admin.dr-ping.com"
RESELLER_ORIGIN = "https://reseller.dr-ping.com"
BOOTSTRAP = "/api/v1/customer/auth/browser-bootstrap"


def settings() -> Settings:
    return Settings(
        environment="test",
        public_app_origin=CUSTOMER_ORIGIN,
        cors_allowed_origins=[CUSTOMER_ORIGIN, ADMIN_ORIGIN, RESELLER_ORIGIN],
    )


def forbidden_dependencies(app: FastAPI, calls: list[str]) -> None:
    def forbidden_db() -> Generator[Session, None, None]:
        calls.append("database")
        raise AssertionError("request opened a database session")
        yield

    def forbidden_limiter() -> routes.RateLimiter:
        calls.append("redis-or-limiter")
        raise AssertionError("request constructed a limiter")

    app.dependency_overrides[get_db_session] = forbidden_db
    app.dependency_overrides[routes.get_customer_rate_limiter] = forbidden_limiter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "extra_headers"),
    [
        (ADMIN_ORIGIN, {}),
        (RESELLER_ORIGIN, {}),
        ("https://evil.dr-ping.com", {}),
        ("https://app.dr-ping.com.evil.example", {}),
        ("https://evil-app.dr-ping.com", {}),
        ("null", {}),
        (None, {}),
        ("not an origin", {}),
        (CUSTOMER_ORIGIN, {"x-vpn-sale-client": "admin-web"}),
        (CUSTOMER_ORIGIN, {"sec-fetch-site": "cross-site"}),
        ("https://user@app.dr-ping.com", {}),
        ("https://app.dr-ping.com/path", {}),
        ("https://app.dr-ping.com?query", {}),
        ("https://app.dr-ping.com#fragment", {}),
    ],
)
async def test_bootstrap_rejects_every_non_customer_origin_before_dependencies(
    origin: str | None, extra_headers: dict[str, str]
) -> None:
    app = create_app(settings())
    calls: list[str] = []
    forbidden_dependencies(app, calls)
    headers = {"x-vpn-sale-client": "customer-web", **extra_headers}
    if origin is not None:
        headers["origin"] = origin

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(BOOTSTRAP, headers=headers)

    assert response.status_code == 403
    assert "set-cookie" not in response.headers
    assert not {"access_token", "csrf_token", "session_id"} & response.json().keys()
    assert origin is None or origin not in response.text
    assert calls == []


@pytest.mark.asyncio
async def test_exact_customer_origin_without_cookie_reaches_application_logic() -> None:
    app = create_app(settings())
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    calls: list[str] = []

    def database() -> Generator[Session, None, None]:
        calls.append("database")
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            BOOTSTRAP,
            headers={"origin": CUSTOMER_ORIGIN, "x-vpn-sale-client": "customer-web"},
        )
    assert response.status_code == 401
    assert calls == ["database"]


@pytest.mark.asyncio
async def test_exact_customer_origin_rotates_valid_refresh_session() -> None:
    configured = settings()
    app = create_app(configured)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    with Session(engine) as session:
        seed_initial_rbac(session)
        original = CustomerAuthService(session, configured).register_password_account(
            "bootstrap.user", "runtime browser passphrase value", email=None
        )
        session.commit()

    def database() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session
            session.commit()

    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as client:
        client.cookies.set(configured.customer_refresh_cookie_name, original.refresh_token)
        response = await client.post(
            BOOTSTRAP,
            headers={"origin": CUSTOMER_ORIGIN, "x-vpn-sale-client": "customer-web"},
        )
    body = response.json()
    assert response.status_code == 200
    assert body["access_token"] and body["csrf_token"]
    assert body["session_id"] != original.session_id
    assert "httponly" in response.headers["set-cookie"].lower()
    assert original.refresh_token not in response.headers["set-cookie"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "path", "method", "request_headers"),
    [
        (CUSTOMER_ORIGIN, BOOTSTRAP, "POST", "X-VPN-Sale-Client, X-CSRF-Token"),
        (
            ADMIN_ORIGIN,
            "/api/v1/admin/configuration/drafts/example/sections",
            "PATCH",
            "Authorization, Content-Type, X-CSRF-Token, X-Request-ID, X-Correlation-ID",
        ),
        (RESELLER_ORIGIN, "/api/v1/reseller/services", "GET", "Authorization, X-Request-ID"),
    ],
)
async def test_first_party_cors_preflight_is_dependency_free(
    origin: str, path: str, method: str, request_headers: str
) -> None:
    app = create_app(settings())
    calls: list[str] = []
    forbidden_dependencies(app, calls)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            path,
            headers={
                "origin": origin,
                "access-control-request-method": method,
                "access-control-request-headers": request_headers,
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert all(header.strip().lower() in allowed_headers for header in request_headers.split(","))
    assert method in response.headers["access-control-allow-methods"]
    assert calls == []


@pytest.mark.asyncio
async def test_cors_rejects_unapproved_origin_and_unsupported_method() -> None:
    app = create_app(settings())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unapproved = await client.options(
            BOOTSTRAP,
            headers={
                "origin": "https://evil.example",
                "access-control-request-method": "POST",
            },
        )
        unsupported = await client.options(
            BOOTSTRAP,
            headers={"origin": CUSTOMER_ORIGIN, "access-control-request-method": "TRACE"},
        )
    assert unapproved.status_code == 400
    assert "access-control-allow-origin" not in unapproved.headers
    assert "access-control-allow-credentials" not in unapproved.headers
    assert unsupported.status_code == 400
