from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from platform_api import telegram_internal
from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import TelegramAccountModel, UserModel


def test_platform_api_imports_with_empty_204_route() -> None:
    from platform_api.main import app

    assert app is not None


@pytest.mark.asyncio
async def test_blocked_route_returns_empty_204(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = "a" * 64
    token_file = tmp_path / "telegram-internal-token"
    token_file.write_text(token)
    application = FastAPI()
    application.include_router(telegram_internal.router)
    application.dependency_overrides[get_settings] = lambda: Settings(
        telegram_internal_token_file=str(token_file)
    )

    class Database:
        def commit(self) -> None:
            pass

    database = Database()
    application.dependency_overrides[get_db_session] = lambda: database
    account = SimpleNamespace(blocked_bot=False)

    def resolved_account(db: object, telegram_id: int) -> tuple[TelegramAccountModel, UserModel]:
        _ = db, telegram_id
        return cast(TelegramAccountModel, account), cast(UserModel, object())

    monkeypatch.setattr(telegram_internal, "_account", resolved_account)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://private"
    ) as client:
        response = await client.post(
            "/api/v1/internal/telegram/identity/blocked",
            headers={"Authorization": f"Bearer {token}", "X-Telegram-Subject": "42"},
        )
    assert response.status_code == 204
    assert response.content == b""
    assert account.blocked_bot is True


def test_internal_routes_are_absent_from_public_openapi() -> None:
    from platform_api.main import create_app

    schema = create_app(Settings()).openapi()
    assert not any(path.startswith("/api/v1/internal/telegram") for path in schema["paths"])
