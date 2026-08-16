from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from platform_api import telegram_account_internal
from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import CustomerSessionModel


class _ScalarRows:
    def __init__(self, rows: list[CustomerSessionModel]) -> None:
        self._rows = rows

    def all(self) -> list[CustomerSessionModel]:
        return list(self._rows)


class _Database:
    def __init__(self, rows: list[CustomerSessionModel]) -> None:
        self.rows = rows
        self.commits = 0

    def scalars(self, statement: object) -> _ScalarRows:
        del statement
        return _ScalarRows(self.rows)

    def commit(self) -> None:
        self.commits += 1


def _session(
    session_id: str,
    user_id: str,
    *,
    revoked: bool = False,
    consumed: bool = False,
    expired: bool = False,
    label: str = "Chrome / Windows",
) -> CustomerSessionModel:
    now = datetime.now(UTC)
    return cast(
        CustomerSessionModel,
        SimpleNamespace(
            id=session_id,
            user_id=user_id,
            device_label=label,
            created_at=now - timedelta(days=2),
            last_used_at=now - timedelta(hours=1),
            idle_expires_at=now - timedelta(minutes=1) if expired else now + timedelta(days=1),
            absolute_expires_at=now + timedelta(days=7),
            revoked_at=now if revoked else None,
            revocation_reason="old" if revoked else None,
            consumed_at=now if consumed else None,
        ),
    )


def _application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, database: _Database
) -> tuple[FastAPI, Settings, str]:
    credential = "a" * 64
    token_file = tmp_path / "telegram-internal-token"
    token_file.write_text(credential)
    settings = Settings(telegram_internal_token_file=str(token_file))
    application = FastAPI()
    application.include_router(telegram_account_internal.router)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_db_session] = lambda: database
    monkeypatch.setattr(
        telegram_account_internal,
        "_customer_id",
        lambda db, telegram_id: "customer-1",
    )
    return application, settings, credential


@pytest.mark.asyncio
async def test_session_list_is_active_owned_opaque_and_no_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        _session("11111111-1111-4111-8111-111111111111", "customer-1"),
        _session("22222222-2222-4222-8222-222222222222", "customer-2"),
        _session("33333333-3333-4333-8333-333333333333", "customer-1", revoked=True),
        _session("44444444-4444-4444-8444-444444444444", "customer-1", consumed=True),
        _session("55555555-5555-4555-8555-555555555555", "customer-1", expired=True),
    ]
    database = _Database(rows)
    application, _settings, credential = _application(tmp_path, monkeypatch, database)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://private"
    ) as client:
        response = await client.get(
            "/api/v1/internal/telegram/sessions",
            headers={
                "Authorization": f"Bearer {credential}",
                "X-Telegram-Subject": "42",
            },
        )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    items = cast(list[dict[str, Any]], response.json()["items"])
    assert len(items) == 1
    assert str(items[0]["reference"]).startswith("ses_")
    assert len(str(items[0]["reference"])) == 28
    assert rows[0].id not in response.text
    assert rows[1].id not in response.text
    assert items[0]["current"] is False


@pytest.mark.asyncio
async def test_revoke_is_owned_idempotent_and_never_accepts_foreign_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    own = _session("66666666-6666-4666-8666-666666666666", "customer-1")
    foreign = _session("77777777-7777-4777-8777-777777777777", "customer-2")
    database = _Database([own, foreign])
    application, settings, credential = _application(tmp_path, monkeypatch, database)
    own_ref = telegram_account_internal.session_reference(settings, own.id)
    foreign_ref = telegram_account_internal.session_reference(settings, foreign.id)
    headers = {
        "Authorization": f"Bearer {credential}",
        "X-Telegram-Subject": "42",
    }

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://private"
    ) as client:
        first = await client.post(
            f"/api/v1/internal/telegram/sessions/{own_ref}/revoke", headers=headers
        )
        repeated = await client.post(
            f"/api/v1/internal/telegram/sessions/{own_ref}/revoke", headers=headers
        )
        denied = await client.post(
            f"/api/v1/internal/telegram/sessions/{foreign_ref}/revoke", headers=headers
        )

    assert first.status_code == 200
    assert first.json() == {"status": "REVOKED"}
    assert first.headers["cache-control"] == "private, no-store"
    assert repeated.status_code == 200
    assert denied.status_code == 404
    assert own.revoked_at is not None
    assert own.revocation_reason == "telegram_customer_revoked"
    assert foreign.revoked_at is None
    assert database.commits == 1
