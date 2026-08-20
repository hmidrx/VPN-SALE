from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import (
    CustomerProfileModel,
    IdentityBase,
    RoleModel,
    TelegramAccountModel,
    UserModel,
    UserRoleAssignmentModel,
)
from platform_api.telegram_onboarding_internal import router

TOKEN = "telegram-onboarding-service-token-with-more-than-32-bytes"  # noqa: S105
TELEGRAM_ID = 42424242


def _application(tmp_path: Path) -> tuple[FastAPI, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(
            RoleModel(
                machine_name="customer",
                display_name="Customer",
                description="Customer role",
                built_in=True,
                active=True,
            )
        )
    token_file = tmp_path / "telegram-internal-token"
    token_file.write_text(TOKEN)
    settings = Settings(telegram_internal_token_file=str(token_file))
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_settings] = lambda: settings

    def database() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    application.dependency_overrides[get_db_session] = database
    return application, factory


def _headers(telegram_id: int = TELEGRAM_ID) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "X-Telegram-Subject": str(telegram_id),
    }


@pytest.mark.asyncio
async def test_first_start_creates_one_pending_customer_and_replay_updates_identity(
    tmp_path: Path,
) -> None:
    application, factory = _application(tmp_path)
    first_body = {
        "telegram_user_id": TELEGRAM_ID,
        "username": "first_name",
        "first_name": "First",
        "last_name": "Customer",
        "language_code": "fa",
        "bot_started": True,
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://private"
    ) as client:
        first = await client.post(
            "/api/v1/internal/telegram/identity/register-or-resolve",
            headers=_headers(),
            json=first_body,
        )
        replay = await client.post(
            "/api/v1/internal/telegram/identity/register-or-resolve",
            headers=_headers(),
            json={
                **first_body,
                "username": "updated_name",
                "last_name": "Updated",
                "language_code": "en",
            },
        )

    assert first.status_code == 200
    assert first.headers["cache-control"] == "private, no-store"
    assert first.json()["account_state"] == "PENDING"
    assert first.json()["created"] is True
    assert len(first.json()["customer_reference"]) == 24
    assert str(TELEGRAM_ID) not in first.json()["customer_reference"]
    assert replay.status_code == 200
    assert replay.json()["created"] is False
    assert replay.json()["customer_reference"] == first.json()["customer_reference"]
    assert replay.json()["locale"] == "en"

    with factory() as db:
        assert db.scalar(select(func.count(UserModel.id))) == 1
        assert db.scalar(select(func.count(TelegramAccountModel.id))) == 1
        assert db.scalar(select(func.count(CustomerProfileModel.user_id))) == 1
        assert db.scalar(select(func.count(UserRoleAssignmentModel.user_id))) == 1
        account = db.scalar(
            select(TelegramAccountModel).where(
                TelegramAccountModel.telegram_user_id == TELEGRAM_ID
            )
        )
        assert account is not None
        assert account.username == "updated_name"
        assert account.last_name == "Updated"
        assert account.language_code == "en"
        assert account.bot_started is True
        assert account.blocked_bot is False


@pytest.mark.asyncio
async def test_restricted_customer_is_not_silently_unblocked_or_rewritten(tmp_path: Path) -> None:
    application, factory = _application(tmp_path)
    body = {
        "telegram_user_id": TELEGRAM_ID,
        "username": "original",
        "first_name": "Original",
        "last_name": None,
        "language_code": "fa",
        "bot_started": True,
    }
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://private"
    ) as client:
        created = await client.post(
            "/api/v1/internal/telegram/identity/register-or-resolve",
            headers=_headers(),
            json=body,
        )
        assert created.status_code == 200
        with factory.begin() as db:
            account = db.scalar(
                select(TelegramAccountModel).where(
                    TelegramAccountModel.telegram_user_id == TELEGRAM_ID
                )
            )
            assert account is not None and account.user_id is not None
            user = db.get(UserModel, account.user_id)
            assert user is not None
            user.status = "BLOCKED"
            account.blocked_bot = True

        restricted = await client.post(
            "/api/v1/internal/telegram/identity/register-or-resolve",
            headers=_headers(),
            json={**body, "username": "should_not_replace"},
        )

    assert restricted.status_code == 200
    assert restricted.json()["account_state"] == "BLOCKED"
    assert restricted.json()["created"] is False
    with factory() as db:
        account = db.scalar(
            select(TelegramAccountModel).where(
                TelegramAccountModel.telegram_user_id == TELEGRAM_ID
            )
        )
        assert account is not None
        assert account.username == "original"
        assert account.blocked_bot is True


@pytest.mark.asyncio
async def test_subject_mismatch_fails_before_identity_creation(tmp_path: Path) -> None:
    application, factory = _application(tmp_path)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://private"
    ) as client:
        response = await client.post(
            "/api/v1/internal/telegram/identity/register-or-resolve",
            headers=_headers(TELEGRAM_ID + 1),
            json={"telegram_user_id": TELEGRAM_ID},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "subject_mismatch"
    with factory() as db:
        assert db.scalar(select(func.count(UserModel.id))) == 0
