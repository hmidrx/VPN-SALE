# pyright: reportPrivateUsage=false
from __future__ import annotations

from collections.abc import Generator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from platform_api import catalog_mapping, telegram_purchase_native_internal
from platform_api.catalog_models import (
    PriceListModel,
    PriceListVersionModel,
    PricingRuleModel,
    ProductCategoryModel,
    ProductModel,
    ProductVersionModel,
)
from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.fulfillment_runtime_models import FulfillmentTargetBindingModel
from platform_api.identity.models import IdentityBase, TelegramAccountModel, UserModel
from platform_api.order_models import OrderModel, WalletPaymentModel
from platform_api.service_models import AllocationPoolModel, AllocationTargetModel
from platform_api.wallet_models import (
    JournalEntryModel,
    WalletBalanceBucketModel,
    WalletBalanceProjectionModel,
    WalletModel,
)

TOKEN = "native-options-integration-token-at-least-32-characters"  # noqa: S105
CUSTOMER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaac1"
TELEGRAM_ID = 525252
GIB = 1024**3
PRICE_RIAL = 1_200_000
PurchaseApp = tuple[FastAPI, sessionmaker[Session], Path]


@pytest.fixture
def purchase_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PurchaseApp:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory.begin() as db:
        user = UserModel(id=CUSTOMER_ID, status="ACTIVE", created_at=now, updated_at=now)
        db.add(user)
        db.add(
            TelegramAccountModel(
                telegram_user_id=TELEGRAM_ID,
                user_id=CUSTOMER_ID,
                first_seen_at=now,
                last_seen_at=now,
                bot_started=True,
                blocked_bot=False,
            )
        )
        category = ProductCategoryModel(
            slug="custom",
            status="ACTIVE",
            customer_visible=True,
            localizations={"fa": {"title": "قابل تنظیم"}},
        )
        db.add(category)
        db.flush()
        product = ProductModel(
            category_id=category.id,
            machine_code="telegram_custom_plan",
            status="ACTIVE",
            customer_visible=True,
            localizations={"fa": {"title": "پلن حرفه‌ای"}},
            availability={},
        )
        db.add(product)
        db.flush()
        version = ProductVersionModel(
            product_id=product.id,
            version_number=1,
            status="PUBLISHED",
            product_type="CUSTOM_PLAN",
            definition_snapshot={},
            options_snapshot={
                "traffic": {
                    "minimum": 10 * GIB,
                    "maximum": 100 * GIB,
                    "step": 10 * GIB,
                    "recommended": [20 * GIB, 50 * GIB],
                },
                "duration_days": {
                    "minimum": 30,
                    "maximum": 180,
                    "step": 30,
                    "recommended": [60, 90],
                },
                "devices": {"minimum": 1, "maximum": 5, "step": 1, "recommended": [1, 2]},
                "location_options": [
                    {"code": "de", "labels": {"fa": "آلمان"}, "enabled": True},
                    {"code": "nl", "labels": {"fa": "هلند"}, "enabled": True},
                ],
                "quality_options": [
                    {"code": "standard", "labels": {"fa": "استاندارد"}, "enabled": True},
                    {"code": "gaming", "labels": {"fa": "گیمینگ"}, "enabled": True},
                ],
                "fixed_traffic_bytes": None,
                "fixed_duration_days": None,
                "fixed_device_count": None,
            },
            constraints_snapshot=[
                {
                    "kind": "LOCATION_MIN_DURATION",
                    "selector_code": "nl",
                    "minimum_duration_days": 60,
                }
            ],
            fulfillment_requirements_snapshot=[{"capability_code": "limit.traffic"}],
            published_at=now,
        )
        db.add(version)
        db.flush()
        product.current_version_id = version.id
        pool = AllocationPoolModel(
            name="telegram-options-test-pool", status="ACTIVE", created_at=now
        )
        db.add(pool)
        db.flush()
        target = AllocationTargetModel(
            pool_id=pool.id,
            panel_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            inbound_id="2",
            provider_kind="sanaei_3x_ui",
            required_protocol="vless",
            role="PRIMARY",
            priority=1,
            weight=1,
            max_capacity=100,
            safety_reserve=0,
            status="ACTIVE",
            certification_minimum="v3.7.0",
            safe_diagnostics={},
        )
        db.add(target)
        db.flush()
        db.add(
            FulfillmentTargetBindingModel(
                product_version_id=version.id,
                location_code="nl",
                quality_code="gaming",
                allocation_target_id=target.id,
                capability_codes=["limit.traffic"],
                active=True,
                created_at=now,
            )
        )

        price_list = PriceListModel(key="retail-native", scope="DEFAULT_RETAIL", active=True)
        db.add(price_list)
        db.flush()
        price_version = PriceListVersionModel(
            price_list_id=price_list.id,
            version_number=1,
            currency="IRR",
            priority=1,
            active=True,
            active_from=now - timedelta(days=1),
        )
        db.add(price_version)
        db.flush()
        db.add(
            PricingRuleModel(
                price_list_version_id=price_version.id,
                code="base",
                rule_type="FIXED_BASE",
                amount_minor=PRICE_RIAL,
                unit_size=1,
                priority=1,
                customer_label={"fa": "قیمت پایه"},
            )
        )

        wallet = WalletModel(customer_id=CUSTOMER_ID, currency="IRR", status="ACTIVE")
        db.add(wallet)
        db.flush()
        db.add(
            WalletBalanceProjectionModel(
                wallet_id=wallet.id,
                posted_balance_rial=10_000_000,
                reserved_balance_rial=0,
                available_balance_rial=10_000_000,
                promotional_balance_rial=0,
                expiring_balance_rial=0,
            )
        )
        db.add(
            WalletBalanceBucketModel(
                wallet_id=wallet.id, bucket_type="CASH", balance_rial=10_000_000
            )
        )

    token_file = tmp_path / "telegram-token"
    token_file.write_text(TOKEN)
    app = FastAPI()
    app.include_router(telegram_purchase_native_internal.router)
    settings = Settings(telegram_internal_token_file=str(token_file))
    app.dependency_overrides[get_settings] = lambda: settings

    def session_dependency() -> Generator[Session, None, None]:
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db_session] = session_dependency
    original_mapping = catalog_mapping.domain_price_list

    def timezone_safe_price_list(db: Session, model: PriceListVersionModel):  # type: ignore[no-untyped-def]
        value = original_mapping(db, model)
        active_from = (
            value.active_from.replace(tzinfo=UTC)
            if value.active_from.tzinfo is None
            else value.active_from
        )
        return replace(value, active_from=active_from)

    monkeypatch.setattr(catalog_mapping, "domain_price_list", timezone_safe_price_list)
    return app, factory, token_file


def headers(key: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {TOKEN}", "X-Telegram-Subject": str(TELEGRAM_ID)}
    if key:
        result["Idempotency-Key"] = key
    return result


def selection(*, duration: int = 60) -> dict[str, int | str]:
    return {
        "traffic_gb": 20,
        "duration_days": duration,
        "device_count": 2,
        "location_code": "nl",
        "quality_code": "gaming",
    }


@pytest.mark.asyncio
async def test_custom_plan_catalog_options_and_authoritative_preview(
    purchase_app: PurchaseApp,
) -> None:
    app, _factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        catalog = await client.get(
            "/api/v1/internal/telegram/purchase-native/catalog", headers=headers()
        )
        assert catalog.status_code == 200, catalog.text
        item = catalog.json()["items"][0]
        assert item["title"] == "پلن حرفه‌ای"
        assert item["configurable"] is True
        assert item["price_toman"] is None

        options = await client.get(
            f"/api/v1/internal/telegram/purchase-native/plans/{item['reference']}",
            headers=headers(),
        )
        assert options.status_code == 200, options.text
        payload = options.json()
        assert payload["traffic_gb"]["minimum"] == 10
        assert payload["traffic_gb"]["step"] == 10
        assert [x["code"] for x in payload["locations"]] == ["de", "nl"]

        preview = await client.post(
            f"/api/v1/internal/telegram/purchase-native/plans/{item['reference']}/preview",
            headers=headers(),
            json=selection(),
        )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["price_toman"] == PRICE_RIAL // 10
    assert plan["traffic_gb"] == 20
    assert plan["duration_days"] == 60
    assert plan["device_limit"] == 2
    assert plan["location_label"] == "هلند"
    assert plan["selection"]["traffic_bytes"] == 20 * GIB


@pytest.mark.asyncio
async def test_invalid_catalog_constraint_is_rejected_before_checkout(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        catalog = await client.get(
            "/api/v1/internal/telegram/purchase-native/catalog", headers=headers()
        )
        reference = catalog.json()["items"][0]["reference"]
        response = await client.post(
            f"/api/v1/internal/telegram/purchase-native/plans/{reference}/preview",
            headers=headers(),
            json=selection(duration=30),
        )
    assert response.status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OrderModel)) == 0
        assert db.scalar(select(func.count()).select_from(WalletPaymentModel)) == 0


@pytest.mark.asyncio
async def test_confirm_replay_debits_once_and_persists_exact_selected_entitlement(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        catalog = await client.get(
            "/api/v1/internal/telegram/purchase-native/catalog", headers=headers()
        )
        reference = catalog.json()["items"][0]["reference"]
        preview = await client.post(
            f"/api/v1/internal/telegram/purchase-native/plans/{reference}/preview",
            headers=headers(),
            json=selection(),
        )
        plan = preview.json()
        body: dict[str, Any] = {
            "plan_reference": reference,
            "reviewed_price_toman": plan["price_toman"],
            "reviewed_selection": plan["selection"],
        }
        first = await client.post(
            "/api/v1/internal/telegram/purchase-native/confirm",
            headers=headers("native-custom-same-key"),
            json=body,
        )
        replay = await client.post(
            "/api/v1/internal/telegram/purchase-native/confirm",
            headers=headers("native-custom-same-key"),
            json=body,
        )
    assert first.status_code == replay.status_code == 200
    assert first.json()["order_reference"] == replay.json()["order_reference"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OrderModel)) == 1
        assert db.scalar(select(func.count()).select_from(WalletPaymentModel)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(JournalEntryModel)
                .where(JournalEntryModel.operation_code == "ORDER_WALLET_CAPTURE")
            )
            == 1
        )
        order = db.scalar(select(OrderModel))
        assert order is not None
        display = cast(dict[str, Any], order.snapshot["telegram_purchase_display"])
        assert display["traffic_gb"] == 20
        assert display["duration_days"] == 60
        assert display["device_limit"] == 2
        assert display["location_code"] == "nl"
        assert display["quality_code"] == "gaming"
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None
        assert projection.posted_balance_rial == 10_000_000 - PRICE_RIAL


@pytest.mark.asyncio
async def test_stale_review_requires_reconfirm_without_wallet_debit(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        catalog = await client.get(
            "/api/v1/internal/telegram/purchase-native/catalog", headers=headers()
        )
        reference = catalog.json()["items"][0]["reference"]
        preview = await client.post(
            f"/api/v1/internal/telegram/purchase-native/plans/{reference}/preview",
            headers=headers(),
            json=selection(),
        )
        plan = preview.json()
        response = await client.post(
            "/api/v1/internal/telegram/purchase-native/confirm",
            headers=headers("native-stale-review"),
            json={
                "plan_reference": reference,
                "reviewed_price_toman": plan["price_toman"] - 1,
                "reviewed_selection": plan["selection"],
            },
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "RECONFIRM_REQUIRED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OrderModel)) == 0
        assert db.scalar(select(func.count()).select_from(WalletPaymentModel)) == 0
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None and projection.posted_balance_rial == 10_000_000
