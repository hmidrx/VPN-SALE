from __future__ import annotations

import hashlib
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from platform_api.activation_models import ServiceActivationRequestModel
from platform_api.delivery_models import DeliveryRevisionModel
from platform_api.fulfillment_runtime_models import FulfillmentEntitlementClockModel
from platform_api.service_models import ServiceAttachmentModel, ServiceModel
from platform_worker import service_activation
from platform_worker.service_activation import ActivationResult, ServiceActivationWorker

SERVICE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ATTACHMENT_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TARGET_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
POOL_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
PANEL_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
PROFILE_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
PROFILE_VERSION_ID = "11111111-1111-4111-8111-111111111111"
PRODUCT_VERSION_ID = "22222222-2222-4222-8222-222222222222"
ORDER_ID = "33333333-3333-4333-8333-333333333333"
ORDER_ITEM_ID = "44444444-4444-4444-8444-444444444444"
CUSTOMER_ID = "55555555-5555-4555-8555-555555555555"
FULFILLMENT_ID = "66666666-6666-4666-8666-666666666666"
REMOTE_IDENTITY = "77777777-7777-4777-8777-777777777777"


class CountingActivator:
    def __init__(self, activation_at: datetime) -> None:
        self.activation_at = activation_at
        self.calls = 0
        self._lock = threading.Lock()

    def activate(
        self,
        request: ServiceActivationRequestModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
    ) -> ActivationResult:
        del request, service
        with self._lock:
            self.calls += 1
        time.sleep(0.2)
        assert attachment.remote_identity_reference is not None
        fingerprint = hashlib.sha256(attachment.remote_identity_reference.encode()).hexdigest()
        return ActivationResult(
            "SUCCESS",
            "AUTHORITATIVE_ACTIVATION_MATCH",
            self.activation_at,
            self.activation_at + timedelta(days=30),
            PROFILE_VERSION_ID,
            fingerprint,
        )


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _create_schema() -> tuple[Engine, sessionmaker[Session], str]:
    url = _postgres_url()
    admin_engine = create_engine(url)
    schema = f"activate_race_{uuid4().hex[:12]}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    statements = (
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
        CREATE TABLE fulfillment_entitlement_clocks (
            fulfillment_request_id uuid PRIMARY KEY,
            starts_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL
        )
        """,
        """
        CREATE TABLE allocation_targets (
            id uuid PRIMARY KEY,
            pool_id uuid NOT NULL,
            panel_id uuid NOT NULL,
            node_id uuid,
            inbound_id varchar(120) NOT NULL,
            provider_kind varchar(64) NOT NULL,
            required_protocol varchar(40) NOT NULL,
            role varchar(32) NOT NULL,
            priority integer NOT NULL,
            weight integer NOT NULL,
            max_capacity integer NOT NULL,
            safety_reserve integer NOT NULL,
            status varchar(32) NOT NULL,
            certification_minimum varchar(80) NOT NULL,
            safe_diagnostics jsonb NOT NULL
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
        """
        CREATE TABLE service_activation_requests (
            id uuid PRIMARY KEY,
            service_id uuid NOT NULL UNIQUE,
            status varchar(40) NOT NULL,
            attempt_count integer NOT NULL,
            lease_owner varchar(96),
            lease_expires_at timestamptz,
            next_attempt_at timestamptz,
            failure_category varchar(64),
            result_code varchar(80),
            correlation_id varchar(96) NOT NULL,
            causation_id varchar(96) NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            completed_at timestamptz
        )
        """,
        """
        CREATE TABLE delivery_profiles (
            id uuid PRIMARY KEY,
            public_reference varchar(48) NOT NULL,
            title varchar(160) NOT NULL,
            status varchar(32) NOT NULL,
            current_version_id uuid,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            version integer NOT NULL
        )
        """,
        """
        CREATE TABLE delivery_profile_versions (
            id uuid PRIMARY KEY,
            profile_id uuid NOT NULL,
            version_number integer NOT NULL,
            status varchar(32) NOT NULL,
            protocol varchar(32) NOT NULL,
            transport varchar(32) NOT NULL,
            security varchar(32) NOT NULL,
            address_source varchar(48) NOT NULL,
            public_address varchar(255) NOT NULL,
            public_port integer NOT NULL,
            display_location varchar(120) NOT NULL,
            remark_template varchar(160) NOT NULL,
            tls_settings jsonb,
            reality_settings jsonb,
            transport_settings jsonb NOT NULL,
            protocol_settings jsonb NOT NULL,
            compatibility_tags jsonb NOT NULL,
            validation_errors jsonb NOT NULL,
            published_at timestamptz,
            created_at timestamptz NOT NULL
        )
        """,
        """
        CREATE TABLE delivery_profile_assignments (
            id uuid PRIMARY KEY,
            profile_version_id uuid NOT NULL,
            target_type varchar(48) NOT NULL,
            target_value varchar(160) NOT NULL,
            active boolean NOT NULL,
            created_at timestamptz NOT NULL,
            CONSTRAINT uq_delivery_assignments_active_target
                UNIQUE (target_type, target_value, active)
        )
        """,
        """
        CREATE TABLE delivery_revisions (
            id uuid PRIMARY KEY,
            service_id uuid NOT NULL,
            revision_number integer NOT NULL,
            status varchar(32) NOT NULL,
            attachment_snapshot jsonb NOT NULL,
            renderer_versions jsonb NOT NULL,
            credential_fingerprints jsonb NOT NULL,
            compatibility_state jsonb NOT NULL,
            reason varchar(80) NOT NULL,
            correlation_reference varchar(96) NOT NULL,
            created_at timestamptz NOT NULL,
            superseded_at timestamptz,
            CONSTRAINT uq_delivery_revisions_service_number
                UNIQUE (service_id, revision_number)
        )
        """,
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.exec_driver_sql(statement)
    return admin_engine, sessionmaker(bind=engine, expire_on_commit=False), schema


def _drop_schema(admin_engine: Engine, schema: str) -> None:
    with admin_engine.begin() as connection:
        connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    admin_engine.dispose()


def _seed(factory: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    with factory.begin() as db:
        db.execute(
            text(
                """
                INSERT INTO services (
                    id, public_reference, lifecycle, beneficiary_customer_id,
                    payer_type, payer_reference, order_id, order_item_id, unit_index,
                    entitlement_snapshot, allocation_policy_snapshot, starts_at, expires_at,
                    activated_at, created_at, version
                ) VALUES (
                    :id, 'svc_activation_race', 'PENDING_ACTIVATION', :customer_id,
                    'CUSTOMER', :payer_reference, :order_id, :item_id, 1,
                    CAST(:entitlement AS jsonb), '{}'::jsonb, NULL, NULL, NULL, :now, 1
                )
                """
            ),
            {
                "id": SERVICE_ID,
                "customer_id": CUSTOMER_ID,
                "payer_reference": CUSTOMER_ID,
                "order_id": ORDER_ID,
                "item_id": ORDER_ITEM_ID,
                "entitlement": '{"product_version_id":"'
                + PRODUCT_VERSION_ID
                + '","duration_days":30,"traffic_quota_bytes":53687091200,"device_limit":1}',
                "now": now,
            },
        )
        db.execute(
            text(
                """
                INSERT INTO service_fulfillment_requests (
                    id, deduplication_key, order_id, order_item_id, unit_index, service_id,
                    event_version, status, correlation_id, causation_id, remote_identity_uuid,
                    attempt_count, created_at, updated_at
                ) VALUES (
                    :id, 'fulfill-race', :order_id, :item_id, 1, :service_id,
                    1, 'SUCCEEDED', 'corr-fulfill', 'cause-order', :remote_id,
                    1, :now, :now
                )
                """
            ),
            {
                "id": FULFILLMENT_ID,
                "order_id": ORDER_ID,
                "item_id": ORDER_ITEM_ID,
                "service_id": SERVICE_ID,
                "remote_id": REMOTE_IDENTITY,
                "now": now,
            },
        )
        db.execute(
            text(
                """
                INSERT INTO allocation_targets (
                    id, pool_id, panel_id, inbound_id, provider_kind, required_protocol,
                    role, priority, weight, max_capacity, safety_reserve, status,
                    certification_minimum, safe_diagnostics
                ) VALUES (
                    :id, :pool_id, :panel_id, '1', 'SANAEI_3X_UI', 'vless',
                    'PRIMARY', 1, 100, 100, 5, 'ACTIVE', 'CONTRACT_VERIFIED', '{}'::jsonb
                )
                """
            ),
            {"id": TARGET_ID, "pool_id": POOL_ID, "panel_id": PANEL_ID},
        )
        db.execute(
            text(
                """
                INSERT INTO service_attachments (
                    id, service_id, allocation_target_id, required, status,
                    verification_status, provider_operation_id, remote_identity_reference,
                    credential_fingerprint, target_snapshot, observed_state,
                    last_reconciled_at, version
                ) VALUES (
                    :id, :service_id, :target_id, true, 'PROVISIONED', 'PENDING_DELIVERY',
                    :fulfillment_id, :remote_id, NULL, '{}'::jsonb,
                    jsonb_build_object('provider_verified', true, 'delivery_verified', false),
                    :now, 1
                )
                """
            ),
            {
                "id": ATTACHMENT_ID,
                "service_id": SERVICE_ID,
                "target_id": TARGET_ID,
                "fulfillment_id": FULFILLMENT_ID,
                "remote_id": REMOTE_IDENTITY,
                "now": now,
            },
        )
        db.execute(
            text(
                """
                INSERT INTO delivery_profiles (
                    id, public_reference, title, status, current_version_id,
                    created_at, updated_at, version
                ) VALUES (
                    :id, 'dprof_activation_race', 'Activation race', 'ACTIVE',
                    :version_id, :now, :now, 1
                )
                """
            ),
            {"id": PROFILE_ID, "version_id": PROFILE_VERSION_ID, "now": now},
        )
        db.execute(
            text(
                """
                INSERT INTO delivery_profile_versions (
                    id, profile_id, version_number, status, protocol, transport, security,
                    address_source, public_address, public_port, display_location,
                    remark_template, tls_settings, reality_settings, transport_settings,
                    protocol_settings, compatibility_tags, validation_errors,
                    published_at, created_at
                ) VALUES (
                    :id, :profile_id, 1, 'PUBLISHED', 'VLESS', 'RAW', 'TLS',
                    'FIXED_DOMAIN', 'edge.example', 443, 'NL', 'VPN {service}',
                    jsonb_build_object(
                        'server_name', 'edge.example',
                        'alpn', jsonb_build_array('h2'),
                        'verify_certificate', true
                    ),
                    NULL, '{}'::jsonb, '{"encryption":"none"}'::jsonb,
                    '[]'::jsonb, '[]'::jsonb, :now, :now
                )
                """
            ),
            {"id": PROFILE_VERSION_ID, "profile_id": PROFILE_ID, "now": now},
        )
        db.execute(
            text(
                """
                INSERT INTO delivery_profile_assignments (
                    id, profile_version_id, target_type, target_value, active, created_at
                ) VALUES (
                    :id, :version_id, 'ALLOCATION_TARGET', :target_id, true, :now
                )
                """
            ),
            {
                "id": str(uuid4()),
                "version_id": PROFILE_VERSION_ID,
                "target_id": TARGET_ID,
                "now": now,
            },
        )


def test_two_postgres_activation_workers_converge_to_one_active_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin_engine, factory, schema = _create_schema()
    try:
        _seed(factory)
        monkeypatch.setattr(service_activation, "MAX_BATCH", 1)
        activation_at = datetime.now(UTC)
        activator = CountingActivator(activation_at)
        first = ServiceActivationWorker(factory, activator, "activation-worker-one")
        second = ServiceActivationWorker(factory, activator, "activation-worker-two")
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []

        def run(worker: ServiceActivationWorker) -> None:
            try:
                barrier.wait(timeout=5)
                worker.run_once()
            except BaseException as exc:  # noqa: BLE001 - collect thread failures
                errors.append(exc)

        threads = [threading.Thread(target=run, args=(worker,)) for worker in (first, second)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert activator.calls == 1

        with factory() as db:
            request = db.scalar(select(ServiceActivationRequestModel))
            service = db.get(ServiceModel, SERVICE_ID)
            attachment = db.get(ServiceAttachmentModel, ATTACHMENT_ID)
            clock = db.get(FulfillmentEntitlementClockModel, FULFILLMENT_ID)
            assert request is not None and request.status == "SUCCEEDED"
            assert service is not None and service.lifecycle == "ACTIVE"
            assert service.starts_at == activation_at
            assert service.activated_at == activation_at
            assert service.expires_at == activation_at + timedelta(days=30)
            assert attachment is not None
            assert attachment.status == "VERIFIED"
            assert attachment.verification_status == "VERIFIED"
            assert clock is not None
            assert clock.starts_at == activation_at
            assert clock.expires_at == activation_at + timedelta(days=30)
            assert db.scalar(select(func.count()).select_from(DeliveryRevisionModel)) == 1
            revision = db.scalar(select(DeliveryRevisionModel))
            assert revision is not None
            assert revision.status == "ACTIVE"
            assert revision.compatibility_state["provider_host_used"] is False

        assert first.run_once() == 0
        assert second.run_once() == 0
        assert activator.calls == 1
    finally:
        _drop_schema(admin_engine, schema)
