# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportArgumentType=false
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from platform_api import telegram_internal
from platform_api.catalog_models import ProductModel
from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import TelegramAccountModel, UserModel


def _app(token_file: Path, database: object) -> FastAPI:
    app = FastAPI()
    app.include_router(telegram_internal.router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_internal_token_file=str(token_file)
    )
    app.dependency_overrides[get_db_session] = lambda: database
    return app


@pytest.mark.asyncio
async def test_purchase_catalog_requires_internal_bearer(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("a" * 64)
    async with AsyncClient(
        transport=ASGITransport(app=_app(token_file, object())), base_url="http://private"
    ) as client:
        response = await client.get(
            "/api/v1/internal/telegram/purchase/catalog",
            headers={"X-Telegram-Subject": "42"},
        )
    assert response.status_code == 401
    assert "a" * 16 not in response.text


@pytest.mark.asyncio
async def test_wrong_telegram_subject_cannot_read_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token = "b" * 64
    token_file = tmp_path / "token"
    token_file.write_text(token)

    def account(db: object, telegram_id: int):  # type: ignore[no-untyped-def]
        _ = db
        if telegram_id != 42:
            raise telegram_internal.HTTPException(status_code=404, detail="account_unlinked")
        return cast(TelegramAccountModel, object()), cast(
            UserModel, SimpleNamespace(id="customer-a", status="ACTIVE")
        )

    monkeypatch.setattr(telegram_internal, "_account", account)
    async with AsyncClient(
        transport=ASGITransport(app=_app(token_file, object())), base_url="http://private"
    ) as client:
        response = await client.get(
            "/api/v1/internal/telegram/purchase/orders/ord_safe",
            headers={"Authorization": f"Bearer {token}", "X-Telegram-Subject": "99"},
        )
    assert response.status_code == 404


def test_native_catalog_rejects_custom_or_multi_option_products() -> None:
    class Database:
        def get(self, model, identifier):  # type: ignore[no-untyped-def]
            _ = model, identifier
            return SimpleNamespace(
                status="PUBLISHED", product_type="CUSTOM_PLAN", options_snapshot={}
            )

    product = cast(
        ProductModel,
        SimpleNamespace(current_version_id="version", localizations={}, machine_code="custom"),
    )
    with pytest.raises(telegram_internal.HTTPException) as exc:
        telegram_internal._native_plan(cast(Any, Database()), product, cast(Any, object()))
    assert exc.value.detail == "selectable_plan_not_supported"


def test_purchase_child_idempotency_keys_are_stable_and_bounded() -> None:
    original = "x" * 120
    quote = telegram_internal._purchase_idempotency_key(original, "quote")
    checkout = telegram_internal._purchase_idempotency_key(original, "checkout")
    assert quote == telegram_internal._purchase_idempotency_key(original, "quote")
    assert quote != checkout
    assert quote != telegram_internal._purchase_idempotency_key(original, "quote", "revision-2")
    assert len(quote) <= 120
    assert original not in quote


def test_max_catalog_machine_code_gets_compact_telegram_reference() -> None:
    machine_code = "p" + "x" * 78
    reference = telegram_internal._plan_reference(machine_code)
    assert len(reference.encode()) == 18
    assert machine_code not in reference


def test_provider_failure_compensation_uses_authoritative_refund_journal() -> None:
    orders = Path("apps/api/src/platform_api/orders.py").read_text()
    cancellation = orders[
        orders.index("def _cancel(") : orders.index(
            "@customer_router.post", orders.index("def _cancel(")
        )
    ]
    assert 'payment.status == "CAPTURED"' in cancellation
    assert "_post_refund(db, order, payment, request)" in cancellation
    assert 'order.financial_status = "REFUNDED"' in cancellation
