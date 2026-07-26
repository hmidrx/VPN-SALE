from collections.abc import Generator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from platform_api.config import Settings
from platform_api.customer_auth import routes
from platform_api.database import get_db_session
from platform_api.identity.models import (
    AccountCredentialModel,
    AuditLogModel,
    CustomerSessionModel,
    IdentityBase,
    SecurityEventModel,
    UserModel,
)
from platform_api.identity.rbac_seed import seed_initial_rbac
from platform_api.main import create_app

ORIGIN = "https://customer.example.test"


def password() -> str:
    return " ".join(("route", "regression", "passphrase", "value"))


@pytest.fixture()
def auth_runtime() -> tuple[FastAPI, Engine, Settings]:
    settings = Settings(
        environment="test",
        public_app_origin=ORIGIN,
        cors_allowed_origins=[ORIGIN],
        public_account_registration_enabled=True,
        password_account_login_enabled=True,
        customer_password_lockout_threshold=2,
        customer_password_login_rate_limit=100,
        customer_refresh_rate_limit=100,
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    with Session(engine) as session:
        seed_initial_rbac(session)
        session.commit()

    app = create_app(settings)

    def database() -> Generator[Session, None, None]:
        session = Session(engine)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[routes.get_customer_rate_limiter] = lambda: routes.InMemoryRateLimiter(
        settings
    )
    return app, engine, settings


async def register(client: AsyncClient, username: str) -> dict[str, str]:
    response = await client.post(
        "/api/v1/customer/auth/register",
        json={"username": username, "password": password()},
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("replay_path", ["refresh", "browser-bootstrap"])
async def test_refresh_reuse_persists_and_revokes_only_its_family(
    auth_runtime: tuple[FastAPI, Engine, Settings],
    replay_path: str,
) -> None:
    app, engine, settings = auth_runtime
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://api.test") as client:
        original = await register(client, "replay.user")
        original_refresh = client.cookies[settings.customer_refresh_cookie_name]
        independent = await client.post(
            "/api/v1/customer/auth/password-login",
            json={"username": "replay.user", "password": password()},
        )
        assert independent.status_code == 200
        independent_access = independent.json()["access_token"]

        rotated = await client.post(
            "/api/v1/customer/auth/refresh",
            json={"refresh_token": original_refresh},
            headers={"x-csrf-token": original["csrf_token"]},
        )
        assert rotated.status_code == 200
        latest = rotated.json()
        latest_refresh = client.cookies[settings.customer_refresh_cookie_name]

        if replay_path == "refresh":
            replay = await client.post(
                "/api/v1/customer/auth/refresh",
                json={"refresh_token": original_refresh},
                headers={"x-csrf-token": original["csrf_token"]},
            )
        else:
            client.cookies.set(settings.customer_refresh_cookie_name, original_refresh)
            replay = await client.post(
                "/api/v1/customer/auth/browser-bootstrap",
                headers={"origin": ORIGIN, "x-vpn-sale-client": "customer-web"},
            )
            client.cookies.set(settings.customer_refresh_cookie_name, latest_refresh)
        assert replay.status_code == 401
        assert "set-cookie" not in replay.headers
        assert not {"access_token", "csrf_token", "session_id"} & replay.json().keys()
        assert original_refresh not in replay.text

        with Session(engine) as verification:
            reused = verification.get(CustomerSessionModel, original["session_id"])
            latest_session = verification.get(CustomerSessionModel, latest["session_id"])
            assert reused is not None and reused.reuse_detected_at is not None
            assert latest_session is not None
            assert reused.session_family_id == latest_session.session_family_id
            family = verification.scalars(
                select(CustomerSessionModel).where(
                    CustomerSessionModel.session_family_id == reused.session_family_id
                )
            ).all()
            assert family and all(row.revoked_at is not None for row in family)
            assert all(row.revocation_reason == "refresh_reuse" for row in family)
            assert verification.scalar(
                select(AuditLogModel).where(
                    AuditLogModel.event_code == "customer.refresh_reuse_detected"
                )
            )
            assert verification.scalar(
                select(SecurityEventModel).where(
                    SecurityEventModel.event_code == "customer.refresh_reuse_detected"
                )
            )

        me = await client.get(
            "/api/v1/customer/auth/me",
            headers={"authorization": f"Bearer {latest['access_token']}"},
        )
        assert me.status_code == 401
        rejected_latest = await client.post(
            "/api/v1/customer/auth/refresh",
            json={"refresh_token": latest_refresh},
            headers={"x-csrf-token": latest["csrf_token"]},
        )
        assert rejected_latest.status_code == 401
        independent_me = await client.get(
            "/api/v1/customer/auth/me",
            headers={"authorization": f"Bearer {independent_access}"},
        )
        assert independent_me.status_code == 200


@pytest.mark.asyncio
async def test_password_failure_state_survives_separate_requests_and_success_resets_it(
    auth_runtime: tuple[FastAPI, Engine, Settings],
) -> None:
    app, engine, _ = auth_runtime
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as client:
        await register(client, "lockout.user")
        for expected_count in (1, 2):
            response = await client.post(
                "/api/v1/customer/auth/password-login",
                json={"username": "lockout.user", "password": password() + " wrong"},
            )
            assert response.status_code == 401
            with Session(engine) as verification:
                credential = verification.scalar(select(AccountCredentialModel))
                assert credential is not None
                assert credential.failed_login_count == expected_count
                assert credential.last_failed_login_at is not None
                assert (credential.lock_until is not None) is (expected_count == 2)

        locked = await client.post(
            "/api/v1/customer/auth/password-login",
            json={"username": "lockout.user", "password": password()},
        )
        unknown = await client.post(
            "/api/v1/customer/auth/password-login",
            json={"username": "unknown.user", "password": password()},
        )
        assert locked.status_code == unknown.status_code == 401
        assert locked.json()["detail"]["message_key"] == unknown.json()["detail"]["message_key"]

        with Session(engine) as unlock:
            credential = unlock.scalar(select(AccountCredentialModel))
            assert credential is not None
            credential.lock_until = None
            unlock.commit()
        success = await client.post(
            "/api/v1/customer/auth/password-login",
            json={"username": "lockout.user", "password": password()},
        )
        assert success.status_code == 200
        with Session(engine) as verification:
            credential = verification.scalar(select(AccountCredentialModel))
            assert credential is not None
            assert credential.failed_login_count == 0
            assert credential.lock_until is None
            codes = verification.scalars(select(SecurityEventModel.event_code)).all()
            assert "customer.password_login.failed" in codes
            assert "customer.password_login.locked" in codes


@pytest.mark.asyncio
async def test_validation_unknown_refresh_and_registration_conflict_are_safe(
    auth_runtime: tuple[FastAPI, Engine, Settings],
) -> None:
    app, engine, _ = auth_runtime
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://api.test") as client:
        invalid = await client.post(
            "/api/v1/customer/auth/register",
            json={"username": [], "password": password()},
        )
        assert invalid.status_code == 422
        with Session(engine) as verification:
            assert verification.scalar(select(UserModel)) is None
            assert verification.scalar(select(CustomerSessionModel)) is None

        await register(client, "conflict.user")
        conflict = await client.post(
            "/api/v1/customer/auth/register",
            json={"username": "CONFLICT.USER", "password": password()},
        )
        assert conflict.status_code == 409
        bad_refresh = await client.post(
            "/api/v1/customer/auth/refresh",
            json={"refresh_token": "unknown-refresh-value"},
            headers={"x-csrf-token": "unknown-csrf-value"},
        )
        assert bad_refresh.status_code == 403
        with Session(engine) as verification:
            assert len(verification.scalars(select(UserModel)).all()) == 1
            conflict_event = verification.scalar(
                select(SecurityEventModel).where(
                    SecurityEventModel.event_code == "customer.registration.conflict"
                )
            )
            assert conflict_event is not None
            serialized = str(conflict_event.metadata_)
            assert "conflict.user" not in serialized
            assert "unknown-refresh-value" not in serialized
