# pyright: reportPrivateUsage=false
from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from platform_api import telegram_internal
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
from platform_api.identity.models import IdentityBase, TelegramAccountModel, UserModel
from platform_api.order_models import OrderModel, TransactionalOutboxModel, WalletPaymentModel
from platform_api.service_models import ServiceModel
from platform_api.services import customer_service_summaries
from platform_api.wallet_models import (
    JournalEntryModel,
    WalletBalanceBucketModel,
    WalletBalanceProjectionModel,
    WalletModel,
)
from platform_worker.order_fulfillment import OrderFulfillmentWorker, ProvisioningResult

TOKEN = "integration-token-with-at-least-thirty-two-characters"  # noqa: S105
CUSTOMER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1"
TELEGRAM_ID = 424242
PRICE_RIAL = 1_200_000
PURCHASE_TEST_TARGET_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1"
PURCHASE_TEST_REMOTE_ID = "cccccccc-cccc-4ccc-8ccc-ccccccccccc1"
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
            slug="fixed",
            status="ACTIVE",
            customer_visible=True,
            localizations={"fa": {"title": "ثابت"}},
        )
        db.add(category)
        db.flush()
        product = ProductModel(
            category_id=category.id,
            machine_code="fixed_plan_with_a_catalog_machine_code_that_is_intentionally_long_but_valid",
            status="ACTIVE",
            customer_visible=True,
            localizations={"fa": {"title": "پلن یک‌ماهه"}},
            availability={},
        )
        db.add(product)
        db.flush()
        version = ProductVersionModel(
            product_id=product.id,
            version_number=1,
            status="PUBLISHED",
            product_type="FIXED_PLAN",
            definition_snapshot={},
            options_snapshot={
                "traffic": {"minimum": 50 * 1024**3, "maximum": 50 * 1024**3, "step": 1},
                "duration_days": {"minimum": 30, "maximum": 30, "step": 1},
                "devices": {"minimum": 1, "maximum": 1, "step": 1},
                "location_options": [{"code": "de", "labels": {"fa": "آلمان"}, "enabled": True}],
                "quality_options": [
                    {"code": "standard", "labels": {"fa": "استاندارد"}, "enabled": True}
                ],
                "fixed_traffic_bytes": 50 * 1024**3,
                "fixed_duration_days": 30,
                "fixed_device_count": 1,
            },
            constraints_snapshot=[],
            fulfillment_requirements_snapshot=[{"capability_code": "limit.traffic"}],
            published_at=now,
        )
        db.add(version)
        db.flush()
        product.current_version_id = version.id
        price_list = PriceListModel(key="retail", scope="DEFAULT_RETAIL", active=True)
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
    app.include_router(telegram_internal.router)
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
    from dataclasses import replace

    from platform_api import catalog_mapping

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


async def plan(client: AsyncClient) -> dict[str, Any]:
    response = await client.get("/api/v1/internal/telegram/purchase/catalog", headers=headers())
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert len(item["reference"].encode()) < 32
    return item


def purchase_body(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_reference": item["reference"],
        "reviewed_price_toman": item["price_toman"],
        "reviewed_selection": item["selection"],
    }


@pytest.mark.asyncio
async def test_db_replay_creates_one_order_and_one_wallet_debit(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        body = purchase_body(item)
        first = await client.post(
            "/api/v1/internal/telegram/purchase/confirm", headers=headers("same-key-001"), json=body
        )
        replay = await client.post(
            "/api/v1/internal/telegram/purchase/confirm", headers=headers("same-key-001"), json=body
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
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None and projection.posted_balance_rial == 10_000_000 - PRICE_RIAL


@pytest.mark.asyncio
async def test_db_reconfirm_required_creates_no_checkout_or_debit(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        body = purchase_body(item)
        body["reviewed_price_toman"] -= 1
        response = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("review-key-001"),
            json=body,
        )
    assert response.status_code == 200
    assert response.json()["outcome"] == "RECONFIRM_REQUIRED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OrderModel)) == 0
        assert db.scalar(select(func.count()).select_from(WalletPaymentModel)) == 0
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None and projection.posted_balance_rial == 10_000_000


class SuccessfulProvisioner:
    calls = 0

    def provision(self, attempt, order, item):  # type: ignore[no-untyped-def]
        self.calls += 1
        starts_at = datetime.now(UTC)
        return ProvisioningResult(
            "SUCCESS",
            "AUTHORITATIVE_RECONCILIATION_MATCH",
            starts_at + timedelta(days=30),
            {
                "allocation_target_id": PURCHASE_TEST_TARGET_ID,
                "provider_kind": "sanaei_3x_ui",
                "panel_reference": "panel_test",
            },
            False,
            PURCHASE_TEST_REMOTE_ID,
            starts_at,
        )


class RejectedProvisioner:
    def provision(self, attempt, order, item):  # type: ignore[no-untyped-def]
        return ProvisioningResult("PERMANENT_FAILURE", "PROVIDER_REJECTED_CREATE")


@pytest.mark.asyncio
async def test_fulfillment_is_exactly_once_and_visible_to_bot_and_service_projection(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        response = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("fulfill-key-001"),
            json=purchase_body(item),
        )
        order_reference = response.json()["order_reference"]
    provider = SuccessfulProvisioner()
    worker = OrderFulfillmentWorker(factory, provider, "test-worker")
    assert worker.run_once() == 1
    assert worker.run_once() == 0
    assert provider.calls == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ServiceModel)) == 1
        summary = customer_service_summaries(db, CUSTOMER_ID)[0]
        assert summary.entitlement.traffic_quota_bytes == 50 * 1024**3
        assert summary.entitlement.duration_days == 30
        assert summary.entitlement.device_limit == 1
        assert summary.entitlement.location_label == "آلمان"
        assert summary.entitlement.quality_label == "استاندارد"
        assert summary.lifecycle == "PENDING_ACTIVATION"
        assert summary.delivery_ready is False
        assert summary.starts_at is None
        assert summary.activated_at is None
        assert summary.expires_at is None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        status_response = await client.get(
            f"/api/v1/internal/telegram/purchase/orders/{order_reference}", headers=headers()
        )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["service_reference"].startswith("svc_")
    assert status_payload["expires_at"] is None
    assert status_payload["service_lifecycle"] == "PENDING_ACTIVATION"
    assert status_payload["delivery_ready"] is False
    assert status_payload["purchase_state"] == "PENDING_DELIVERY"


@pytest.mark.asyncio
async def test_definitive_failure_refunds_exactly_once(purchase_app: PurchaseApp) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("refund-key-001"),
            json=purchase_body(item),
        )
    worker = OrderFulfillmentWorker(factory, RejectedProvisioner(), "refund-worker")
    assert worker.run_once() == 1
    assert worker.run_once() == 0
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(JournalEntryModel)
                .where(JournalEntryModel.operation_code == "ORDER_WALLET_REFUND")
            )
            == 1
        )
        payment = db.scalar(select(WalletPaymentModel))
        order = db.scalar(select(OrderModel))
        assert payment is not None and payment.refund_journal_id is not None
        assert order is not None and order.status == "REFUNDED"


@pytest.mark.asyncio
async def test_two_workers_and_stale_claim_recovery(purchase_app: PurchaseApp) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("claim-key-001"),
            json=purchase_body(item),
        )
    first = OrderFulfillmentWorker(factory, SuccessfulProvisioner(), "worker-one")
    second = OrderFulfillmentWorker(factory, SuccessfulProvisioner(), "worker-two")
    claimed = first._claim()
    assert len(claimed) == 1
    assert second._claim() == []
    with factory.begin() as db:
        event = db.get(TransactionalOutboxModel, claimed[0])
        assert event is not None
        event.claimed_at = datetime.now(UTC) - timedelta(minutes=6)
    assert second._claim() == claimed


@pytest.mark.asyncio
async def test_db_committed_retry_wins_over_later_catalog_change(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        body = purchase_body(item)
        first = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("lost-response-1"),
            json=body,
        )
        with factory.begin() as db:
            product = db.scalar(select(ProductModel))
            assert product is not None
            product.status = "PAUSED"
            rule = db.scalar(select(PricingRuleModel))
            assert rule is not None
            rule.amount_minor += 900_000
        retry = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("lost-response-1"),
            json=body,
        )
        historical = await client.get(
            f"/api/v1/internal/telegram/purchase/orders/{first.json()['order_reference']}",
            headers=headers(),
        )
    assert retry.status_code == 200
    assert retry.json()["order_reference"] == first.json()["order_reference"]
    assert retry.json()["outcome"] == "ACCEPTED"
    assert historical.status_code == 200
    assert historical.json()["plan"]["title"] == "پلن یک‌ماهه"


@pytest.mark.asyncio
async def test_db_insufficient_balance_after_review_is_authoritative_409(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        with factory.begin() as db:
            projection = db.scalar(select(WalletBalanceProjectionModel))
            bucket = db.scalar(select(WalletBalanceBucketModel))
            assert projection is not None and bucket is not None
            projection.posted_balance_rial = projection.available_balance_rial = 0
            bucket.balance_rial = 0
        response = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("insufficient-1"),
            json=purchase_body(item),
        )
    assert response.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(OrderModel)) == 0
        assert db.scalar(select(func.count()).select_from(WalletPaymentModel)) == 0


@pytest.mark.asyncio
async def test_db_same_external_key_cannot_buy_changed_revision_twice(
    purchase_app: PurchaseApp,
) -> None:
    app, factory, _ = purchase_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        item = await plan(client)
        original_body = purchase_body(item)
        first = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("global-economic-key"),
            json=original_body,
        )
        assert first.status_code == 200
        with factory() as db:
            projection = db.scalar(select(WalletBalanceProjectionModel))
            assert projection is not None
            balance_after_first = projection.posted_balance_rial

        changed_body = {
            **original_body,
            "reviewed_price_toman": original_body["reviewed_price_toman"] + 70_000,
            "reviewed_selection": {
                **original_body["reviewed_selection"],
                "duration_days": 60,
            },
        }
        second = await client.post(
            "/api/v1/internal/telegram/purchase/confirm",
            headers=headers("global-economic-key"),
            json=changed_body,
        )

    assert second.status_code == 200
    assert second.json()["order_reference"] == first.json()["order_reference"]
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
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None
        assert projection.posted_balance_rial == balance_after_first
