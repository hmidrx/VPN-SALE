from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import IdentityBase, TelegramAccountModel, UserModel
from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import ServiceModel, ServiceOperationModel
from platform_api.service_operation_payment_models import ServiceOperationPaymentModel
from platform_api.telegram_service_operation_payment_internal import router
from platform_api.wallet_models import (
    JournalEntryModel,
    LedgerPostingModel,
    WalletBalanceBucketModel,
    WalletBalanceProjectionModel,
    WalletModel,
    WalletReservationModel,
)

TOKEN = "service-operation-payment-integration-token-0001"  # noqa: S105
CUSTOMER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
OTHER_CUSTOMER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"
TELEGRAM_ID = 424242
OTHER_TELEGRAM_ID = 434343
SERVICE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"
OPERATION_ID = "cccccccc-cccc-4ccc-8ccc-ccccccccccc1"
PRICE_RIAL = 600_000
INITIAL_BALANCE = 2_000_000
PaymentApp = tuple[FastAPI, sessionmaker[Session]]


@pytest.fixture
def payment_app(tmp_path: Path) -> PaymentApp:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory.begin() as db:
        db.add_all(
            [
                UserModel(id=CUSTOMER_ID, status="ACTIVE", created_at=now, updated_at=now),
                UserModel(id=OTHER_CUSTOMER_ID, status="ACTIVE", created_at=now, updated_at=now),
                TelegramAccountModel(
                    telegram_user_id=TELEGRAM_ID,
                    user_id=CUSTOMER_ID,
                    first_seen_at=now,
                    last_seen_at=now,
                    bot_started=True,
                    blocked_bot=False,
                ),
                TelegramAccountModel(
                    telegram_user_id=OTHER_TELEGRAM_ID,
                    user_id=OTHER_CUSTOMER_ID,
                    first_seen_at=now,
                    last_seen_at=now,
                    bot_started=True,
                    blocked_bot=False,
                ),
            ]
        )
        service = ServiceModel(
            id=SERVICE_ID,
            public_reference="svc_payment_test",
            lifecycle="ACTIVE",
            beneficiary_customer_id=CUSTOMER_ID,
            payer_type="CUSTOMER",
            payer_reference=CUSTOMER_ID,
            order_id="dddddddd-dddd-4ddd-8ddd-ddddddddddd1",
            order_item_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeee1",
            unit_index=1,
            entitlement_snapshot={},
            starts_at=now - timedelta(days=10),
            expires_at=now + timedelta(days=20),
            activated_at=now - timedelta(days=10),
            created_at=now - timedelta(days=10),
            version=3,
        )
        db.add(service)
        db.add(
            ServiceOperationModel(
                id=OPERATION_ID,
                service_id=SERVICE_ID,
                operation_type="RENEW",
                status="AWAITING_PAYMENT",
                requester_type="CUSTOMER",
                requester_id=CUSTOMER_ID,
                idempotency_key_digest="sha256:quote-operation-key",
                reason_code="TELEGRAM_SELF_SERVICE",
                policy_version_id="ffffffff-ffff-4fff-8fff-fffffffffff1",
                policy_snapshot={"high_risk_operations": []},
                desired_change={
                    "traffic_delta_bytes": 0,
                    "duration_delta_seconds": 30 * 24 * 60 * 60,
                    "renew_days": 30,
                },
                quote_snapshot={
                    "quote_id": "11111111-1111-4111-8111-111111111111",
                    "price_rial": PRICE_RIAL,
                    "currency": "IRR",
                    "expires_at": (now + timedelta(minutes=15)).isoformat(),
                    "service_version": 3,
                },
                created_at=now,
                updated_at=now,
                version=1,
            )
        )
        wallet = WalletModel(customer_id=CUSTOMER_ID, currency="IRR", status="ACTIVE")
        db.add(wallet)
        db.flush()
        db.add(
            WalletBalanceProjectionModel(
                wallet_id=wallet.id,
                posted_balance_rial=INITIAL_BALANCE,
                reserved_balance_rial=0,
                available_balance_rial=INITIAL_BALANCE,
                promotional_balance_rial=0,
                expiring_balance_rial=0,
            )
        )
        db.add(
            WalletBalanceBucketModel(
                wallet_id=wallet.id,
                bucket_type="CASH",
                balance_rial=INITIAL_BALANCE,
            )
        )

    token_file = tmp_path / "telegram-token"
    token_file.write_text(TOKEN)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: Settings(
        telegram_internal_token_file=str(token_file)
    )

    def session_dependency() -> Generator[Session, None, None]:
        with factory() as db:
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback()
                raise

    app.dependency_overrides[get_db_session] = session_dependency
    return app, factory


def _headers(telegram_id: int = TELEGRAM_ID, key: str = "payment-idempotency-key-001") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "X-Telegram-Subject": str(telegram_id),
        "Idempotency-Key": key,
    }


async def _pay(client: AsyncClient, headers: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
    return await client.post(
        f"/api/v1/internal/telegram/service-management/operations/{OPERATION_ID}/pay",
        headers=headers or _headers(),
    )


@pytest.mark.asyncio
async def test_payment_captures_wallet_once_and_queues_one_outbox_event(
    payment_app: PaymentApp,
) -> None:
    app, factory = payment_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        first = await _pay(client)
        replay = await _pay(client, _headers(key="different-retry-key-002"))

    assert first.status_code == replay.status_code == 200
    assert first.json()["payment_reference"] == replay.json()["payment_reference"]
    assert first.json()["status"] == "QUEUED"
    assert first.json()["amount_rial"] == PRICE_RIAL

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ServiceOperationPaymentModel)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(JournalEntryModel)
                .where(JournalEntryModel.operation_code == "SERVICE_OPERATION_WALLET_CAPTURE")
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(TransactionalOutboxModel)
                .where(TransactionalOutboxModel.event_type == "service_operation.ready.v1")
            )
            == 1
        )
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None
        assert projection.posted_balance_rial == INITIAL_BALANCE - PRICE_RIAL
        assert projection.available_balance_rial == INITIAL_BALANCE - PRICE_RIAL
        assert projection.reserved_balance_rial == 0
        reservation = db.scalar(select(WalletReservationModel))
        assert reservation is not None and reservation.status == "CAPTURED"
        postings = list(db.scalars(select(LedgerPostingModel)))
        debits = sum(row.amount_rial for row in postings if row.direction == "DEBIT")
        credits = sum(row.amount_rial for row in postings if row.direction == "CREDIT")
        assert debits == credits == PRICE_RIAL
        operation = db.get(ServiceOperationModel, OPERATION_ID)
        assert operation is not None and operation.status == "QUEUED"


@pytest.mark.asyncio
async def test_stale_service_version_is_rejected_before_wallet_mutation(
    payment_app: PaymentApp,
) -> None:
    app, factory = payment_app
    with factory.begin() as db:
        operation = db.get(ServiceOperationModel, OPERATION_ID)
        assert operation is not None
        operation.quote_snapshot = {**operation.quote_snapshot, "service_version": 2}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        response = await _pay(client)

    assert response.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ServiceOperationPaymentModel)) == 0
        assert db.scalar(select(func.count()).select_from(JournalEntryModel)) == 0
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None and projection.posted_balance_rial == INITIAL_BALANCE


@pytest.mark.asyncio
async def test_insufficient_wallet_balance_creates_no_financial_records(
    payment_app: PaymentApp,
) -> None:
    app, factory = payment_app
    with factory.begin() as db:
        projection = db.scalar(select(WalletBalanceProjectionModel))
        bucket = db.scalar(select(WalletBalanceBucketModel).where(WalletBalanceBucketModel.bucket_type == "CASH"))
        assert projection is not None and bucket is not None
        projection.posted_balance_rial = PRICE_RIAL - 1
        projection.available_balance_rial = PRICE_RIAL - 1
        bucket.balance_rial = PRICE_RIAL - 1

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        response = await _pay(client)

    assert response.status_code == 402
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ServiceOperationPaymentModel)) == 0
        assert db.scalar(select(func.count()).select_from(JournalEntryModel)) == 0
        assert db.scalar(select(func.count()).select_from(WalletReservationModel)) == 0


@pytest.mark.asyncio
async def test_other_telegram_customer_cannot_pay_operation(
    payment_app: PaymentApp,
) -> None:
    app, factory = payment_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://private") as client:
        response = await _pay(client, _headers(OTHER_TELEGRAM_ID, "other-customer-payment-key"))

    assert response.status_code == 404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ServiceOperationPaymentModel)) == 0
        projection = db.scalar(select(WalletBalanceProjectionModel))
        assert projection is not None and projection.posted_balance_rial == INITIAL_BALANCE
