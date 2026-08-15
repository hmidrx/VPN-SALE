from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from platform_api.order_models import OrderItemModel, OrderModel, TransactionalOutboxModel
from platform_api.service_models import ServiceFulfillmentRequestModel, ServiceModel
from platform_worker import order_fulfillment
from platform_worker.order_fulfillment import EVENT_TYPE, OrderFulfillmentWorker, ProvisioningResult

TARGET_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CUSTOMER_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PRODUCT_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PRODUCT_VERSION_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
QUOTE_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


class CountingProvisioner:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def provision(
        self, attempt: ServiceFulfillmentRequestModel, order: OrderModel, item: OrderItemModel
    ) -> ProvisioningResult:
        _ = order, item
        with self._lock:
            self.calls += 1
        time.sleep(0.2)
        starts_at = datetime.now(UTC)
        return ProvisioningResult(
            "SUCCESS",
            "AUTHORITATIVE_RECONCILIATION_MATCH",
            starts_at + timedelta(days=30),
            {
                "allocation_target_id": TARGET_ID,
                "provider_kind": "sanaei_3x_ui",
                "panel_reference": "panel_safe",
            },
            False,
            attempt.remote_identity_uuid,
            starts_at,
        )


class CrashAfterRemoteSuccessProvisioner:
    """First call creates remotely then crashes before local finalization; retry reconciles."""

    def __init__(self) -> None:
        self.remote_exists = False
        self.create_calls = 0
        self.reconcile_calls = 0

    def provision(
        self, attempt: ServiceFulfillmentRequestModel, order: OrderModel, item: OrderItemModel
    ) -> ProvisioningResult:
        _ = order, item
        if not self.remote_exists:
            self.remote_exists = True
            self.create_calls += 1
            raise RuntimeError("simulated crash after remote create")
        self.reconcile_calls += 1
        return ProvisioningResult(
            "SUCCESS",
            "AUTHORITATIVE_RECONCILIATION_MATCH",
            None,
            {
                "allocation_target_id": TARGET_ID,
                "provider_kind": "sanaei_3x_ui",
                "panel_reference": "panel_safe",
                "entitlement_start_policy": "DELIVERY_ACTIVATION",
            },
            False,
            attempt.remote_identity_uuid,
            None,
        )


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _create_race_schema() -> tuple[Engine, sessionmaker[Session], str]:
    url = _postgres_url()
    admin_engine = create_engine(url)
    schema = f"fulfill_race_{uuid4().hex[:12]}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    statements = (
        """
        CREATE TABLE orders (
            id uuid PRIMARY KEY,
            reference varchar(40) NOT NULL,
            customer_id uuid NOT NULL,
            quote_id uuid NOT NULL,
            quote_reference varchar(64) NOT NULL,
            status varchar(40) NOT NULL,
            financial_status varchar(40) NOT NULL,
            fulfillment_status varchar(40) NOT NULL,
            payment_method varchar(24) NOT NULL,
            currency varchar(3) NOT NULL,
            subtotal_rial bigint NOT NULL,
            adjustment_total_rial bigint NOT NULL,
            final_amount_rial bigint NOT NULL,
            snapshot jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            paid_at timestamptz,
            cancelled_at timestamptz,
            version integer NOT NULL
        )
        """,
        """
        CREATE TABLE order_items (
            id uuid PRIMARY KEY,
            order_id uuid NOT NULL,
            product_id uuid NOT NULL,
            product_version_id uuid NOT NULL,
            product_machine_code varchar(80) NOT NULL,
            snapshot jsonb NOT NULL,
            position integer NOT NULL
        )
        """,
        """
        CREATE TABLE transactional_outbox (
            id uuid PRIMARY KEY,
            event_key varchar(120) NOT NULL UNIQUE,
            event_type varchar(120) NOT NULL,
            status varchar(24) NOT NULL,
            payload jsonb NOT NULL,
            attempt_count integer NOT NULL,
            available_at timestamptz NOT NULL,
            claimed_at timestamptz,
            processed_at timestamptz,
            failure_category varchar(64),
            created_at timestamptz NOT NULL
        )
        """,
        """
        CREATE TABLE services (
            id uuid PRIMARY KEY,
            public_reference varchar(48) NOT NULL UNIQUE,
            lifecycle varchar(40) NOT NULL,
            beneficiary_customer_id uuid NOT NULL,
            payer_type varchar(32) NOT NULL,
            payer_reference varchar(80) NOT NULL,
            reseller_id uuid,
            order_id uuid NOT NULL,
            order_item_id uuid NOT NULL,
            unit_index integer NOT NULL,
            entitlement_snapshot jsonb NOT NULL,
            allocation_policy_snapshot jsonb,
            starts_at timestamptz,
            expires_at timestamptz,
            activated_at timestamptz,
            created_at timestamptz NOT NULL,
            version integer NOT NULL,
            CONSTRAINT uq_services_order_item_unit UNIQUE (order_item_id, unit_index)
        )
        """,
        """
        CREATE TABLE service_fulfillment_requests (
            id uuid PRIMARY KEY,
            deduplication_key varchar(160) NOT NULL UNIQUE,
            order_id uuid NOT NULL,
            order_item_id uuid NOT NULL,
            unit_index integer NOT NULL,
            service_id uuid,
            event_version integer NOT NULL,
            status varchar(40) NOT NULL,
            correlation_id varchar(96) NOT NULL,
            causation_id varchar(96) NOT NULL,
            lease_owner varchar(96),
            lease_expires_at timestamptz,
            result_code varchar(80),
            remote_identity_uuid uuid NOT NULL,
            attempt_count integer NOT NULL,
            failure_category varchar(64),
            next_attempt_at timestamptz,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT uq_service_fulfillment_item_unit UNIQUE (order_item_id, unit_index)
        )
        """,
        """
        CREATE TABLE service_attachments (
            id uuid PRIMARY KEY,
            service_id uuid NOT NULL,
            allocation_target_id uuid NOT NULL,
            required boolean NOT NULL,
            status varchar(40) NOT NULL,
            verification_status varchar(40) NOT NULL,
            provider_operation_id uuid,
            remote_identity_reference varchar(160),
            credential_fingerprint varchar(120),
            target_snapshot jsonb NOT NULL,
            observed_state jsonb NOT NULL,
            last_reconciled_at timestamptz,
            version integer NOT NULL,
            CONSTRAINT uq_service_attachments_target UNIQUE (service_id, allocation_target_id),
            CONSTRAINT uq_service_attachments_remote_identity
                UNIQUE (allocation_target_id, remote_identity_reference)
        )
        """,
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    return admin_engine, sessionmaker(bind=engine, expire_on_commit=False), schema


def _drop_race_schema(admin_engine: Engine, schema: str) -> None:
    with admin_engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    admin_engine.dispose()


def _seed_duplicate_events(factory: sessionmaker[Session]) -> tuple[str, str]:
    now = datetime.now(UTC)
    with factory.begin() as db:
        order = OrderModel(
            reference="ord_pg_race",
            customer_id=CUSTOMER_ID,
            quote_id=QUOTE_ID,
            quote_reference="quote_pg_race",
            status="READY_FOR_FULFILLMENT",
            financial_status="PAID",
            fulfillment_status="READY",
            payment_method="WALLET",
            currency="IRR",
            subtotal_rial=1_000_000,
            adjustment_total_rial=0,
            final_amount_rial=1_000_000,
            snapshot={
                "telegram_purchase_display": {
                    "title": "پلن تست",
                    "location_label": "آلمان",
                    "quality_label": "استاندارد",
                }
            },
            created_at=now,
            paid_at=now,
            cancelled_at=None,
            version=1,
        )
        db.add(order)
        db.flush()
        item = OrderItemModel(
            order_id=order.id,
            product_id=PRODUCT_ID,
            product_version_id=PRODUCT_VERSION_ID,
            product_machine_code="safe-plan",
            snapshot={
                "product_version_id": PRODUCT_VERSION_ID,
                "product_machine_code": "safe-plan",
                "selected_options": {
                    "traffic_bytes": 50 * 1024**3,
                    "duration_days": 30,
                    "device_count": 1,
                    "location_code": "de",
                    "quality_code": "standard",
                },
            },
            position=1,
        )
        db.add(item)
        db.flush()
        for suffix in ("a", "b"):
            db.add(
                TransactionalOutboxModel(
                    event_key=f"duplicate-ready-{suffix}",
                    event_type=EVENT_TYPE,
                    status="PENDING",
                    payload={"order_id": order.id, "correlation_id": f"corr-{suffix}"},
                    attempt_count=0,
                    available_at=now - timedelta(seconds=1),
                    claimed_at=None,
                    processed_at=None,
                    failure_category=None,
                    created_at=now,
                )
            )
        return order.id, item.id


def test_two_distinct_outbox_rows_converge_with_two_postgres_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_engine, factory, schema = _create_race_schema()
    try:
        order_id, item_id = _seed_duplicate_events(factory)
        monkeypatch.setattr(order_fulfillment, "MAX_BATCH", 1)
        provider = CountingProvisioner()
        first = OrderFulfillmentWorker(factory, provider, "pg-worker-one")
        second = OrderFulfillmentWorker(factory, provider, "pg-worker-two")
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def run(worker: OrderFulfillmentWorker) -> None:
            try:
                barrier.wait(timeout=5)
                worker.run_once()
            except BaseException as exc:  # noqa: BLE001 - test captures thread failures
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(worker,)) for worker in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert provider.calls == 1

        expected_identity = str(uuid5(NAMESPACE_URL, f"vpnsale:fulfillment:{order_id}:{item_id}:1"))
        with factory.begin() as db:
            attempts = list(db.scalars(select(ServiceFulfillmentRequestModel)))
            assert len(attempts) == 1
            assert attempts[0].remote_identity_uuid == expected_identity
            assert db.scalar(select(func.count()).select_from(ServiceModel)) == 1
            for event in db.scalars(
                select(TransactionalOutboxModel).where(TransactionalOutboxModel.status == "PENDING")
            ):
                event.available_at = datetime.now(UTC) - timedelta(seconds=1)
                event.claimed_at = None

        first.run_once()
        assert provider.calls == 1
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(TransactionalOutboxModel)
                    .where(TransactionalOutboxModel.status == "PROCESSED")
                )
                == 2
            )
            assert db.scalar(select(func.count()).select_from(ServiceModel)) == 1
    finally:
        _drop_race_schema(admin_engine, schema)


def test_crash_after_remote_success_reuses_identity_and_reconciles_before_second_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_engine, factory, schema = _create_race_schema()
    try:
        order_id, item_id = _seed_duplicate_events(factory)
        monkeypatch.setattr(order_fulfillment, "MAX_BATCH", 1)
        started = datetime.now(UTC)
        provider = CrashAfterRemoteSuccessProvisioner()
        first = OrderFulfillmentWorker(factory, provider, "crash-worker", now=lambda: started)

        with pytest.raises(RuntimeError, match="simulated crash"):
            first.run_once()

        expected_identity = str(uuid5(NAMESPACE_URL, f"vpnsale:fulfillment:{order_id}:{item_id}:1"))
        with factory() as db:
            attempt = db.scalar(select(ServiceFulfillmentRequestModel))
            assert attempt is not None
            assert attempt.status == "IN_PROGRESS"
            assert attempt.remote_identity_uuid == expected_identity
            assert db.scalar(select(func.count()).select_from(ServiceModel)) == 0
        assert provider.remote_exists is True
        assert provider.create_calls == 1

        recovered_at = started + order_fulfillment.LEASE + timedelta(seconds=1)
        second = OrderFulfillmentWorker(
            factory,
            provider,
            "recovery-worker",
            now=lambda: recovered_at,
        )
        assert second.run_once() == 1
        assert provider.create_calls == 1
        assert provider.reconcile_calls == 1
        assert second.run_once() == 0
        assert provider.create_calls == 1

        with factory() as db:
            attempt = db.scalar(select(ServiceFulfillmentRequestModel))
            service = db.scalar(select(ServiceModel))
            assert attempt is not None and attempt.status == "SUCCEEDED"
            assert attempt.remote_identity_uuid == expected_identity
            assert service is not None
            assert service.lifecycle == "PENDING_ACTIVATION"
            assert service.starts_at is None
            assert service.expires_at is None
    finally:
        _drop_race_schema(admin_engine, schema)
