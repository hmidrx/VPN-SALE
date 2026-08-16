from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.delivery import DeliveryError, DeliveryErrorCode, DeliveryOutputFormat

from platform_api.delivery_models import (
    DeliveryAccessEventModel,
    DeliverySubscriptionModel,
    DeliverySubscriptionTokenModel,
)
from platform_api.delivery_resolution import RENDERER_VERSION
from platform_api.delivery_subscriptions import (
    issue_service_subscription,
    render_public_subscription,
    revoke_service_subscription,
    rotate_service_subscription,
)

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
REMOTE_IDENTITY = "66666666-6666-4666-8666-666666666666"


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _create_schema() -> tuple[Engine, sessionmaker[Session], str]:
    admin_engine = create_engine(_postgres_url())
    schema = f"subscription_security_{uuid4().hex[:12]}"
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_engine(
        _postgres_url(),
        connect_args={"options": f"-csearch_path={schema}"},
    )
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
            version integer NOT NULL
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
            superseded_at timestamptz
        )
        """,
        """
        CREATE TABLE delivery_subscriptions (
            id uuid PRIMARY KEY,
            public_reference varchar(48) NOT NULL UNIQUE,
            service_id uuid NOT NULL,
            scope varchar(32) NOT NULL,
            status varchar(32) NOT NULL,
            active_token_hash varchar(96),
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL,
            CONSTRAINT uq_delivery_subscriptions_service_scope UNIQUE (service_id, scope)
        )
        """,
        """
        CREATE TABLE delivery_subscription_tokens (
            id uuid PRIMARY KEY,
            subscription_id uuid NOT NULL,
            token_hash varchar(96) NOT NULL UNIQUE,
            status varchar(32) NOT NULL,
            issued_at timestamptz NOT NULL,
            grace_expires_at timestamptz,
            revoked_at timestamptz
        )
        """,
        """
        CREATE TABLE delivery_access_events (
            id uuid PRIMARY KEY,
            subscription_id uuid,
            service_id uuid,
            actor_type varchar(32) NOT NULL,
            action varchar(48) NOT NULL,
            outcome varchar(32) NOT NULL,
            safe_metadata jsonb NOT NULL,
            created_at timestamptz NOT NULL
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
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    fingerprint = hashlib.sha256(REMOTE_IDENTITY.encode()).hexdigest()
    with factory.begin() as db:
        db.execute(
            text(
                """
                INSERT INTO services (
                    id, public_reference, lifecycle, beneficiary_customer_id, payer_type,
                    payer_reference, order_id, order_item_id, unit_index, entitlement_snapshot,
                    allocation_policy_snapshot, starts_at, expires_at, activated_at, created_at,
                    version
                ) VALUES (
                    :id, 'svc_subscription_safe', 'ACTIVE', :customer_id, 'CUSTOMER',
                    :customer_ref, :order_id, :item_id, 1,
                    jsonb_build_object(
                        'product_version_id', CAST(:product_version AS text)
                    ),
                    '{}'::jsonb, :now, :expires, :now, :now, 1
                )
                """
            ),
            {
                "id": SERVICE_ID,
                "customer_id": CUSTOMER_ID,
                "customer_ref": CUSTOMER_ID,
                "order_id": ORDER_ID,
                "item_id": ORDER_ITEM_ID,
                "product_version": PRODUCT_VERSION_ID,
                "now": now,
                "expires": now + timedelta(days=30),
            },
        )
        db.execute(
            text(
                """
                INSERT INTO allocation_targets (
                    id, pool_id, panel_id, inbound_id, provider_kind, required_protocol, role,
                    priority, weight, max_capacity, safety_reserve, status,
                    certification_minimum, safe_diagnostics
                ) VALUES (
                    :id, :pool_id, :panel_id, '1', 'SANAEI_3X_UI', 'vless', 'PRIMARY',
                    1, 100, 100, 5, 'ACTIVE', 'CONTRACT_VERIFIED', '{}'::jsonb
                )
                """
            ),
            {"id": TARGET_ID, "pool_id": POOL_ID, "panel_id": PANEL_ID},
        )
        db.execute(
            text(
                """
                INSERT INTO service_attachments (
                    id, service_id, allocation_target_id, required, status, verification_status,
                    remote_identity_reference, target_snapshot, observed_state,
                    last_reconciled_at, version
                ) VALUES (
                    :id, :service_id, :target_id, true, 'VERIFIED', 'VERIFIED', :remote_id,
                    '{}'::jsonb, '{}'::jsonb, :now, 1
                )
                """
            ),
            {
                "id": ATTACHMENT_ID,
                "service_id": SERVICE_ID,
                "target_id": TARGET_ID,
                "remote_id": REMOTE_IDENTITY,
                "now": now,
            },
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
                    NULL, '{}'::jsonb, jsonb_build_object('encryption', 'none'),
                    '[]'::jsonb, '[]'::jsonb, :now, :now
                )
                """
            ),
            {"id": PROFILE_VERSION_ID, "profile_id": PROFILE_ID, "now": now},
        )
        db.execute(
            text(
                """
                INSERT INTO delivery_revisions (
                    id, service_id, revision_number, status, attachment_snapshot,
                    renderer_versions, credential_fingerprints, compatibility_state, reason,
                    correlation_reference, created_at
                ) VALUES (
                    :id, :service_id, 1, 'ACTIVE',
                    jsonb_build_object(
                        'attachment_id', CAST(:attachment_id AS text),
                        'allocation_target_id', CAST(:target_id AS text),
                        'profile_version_id', CAST(:profile_version_id AS text)
                    ),
                    jsonb_build_object('URI', CAST(:renderer AS text)),
                    jsonb_build_object(
                        CAST(:attachment_id AS text), CAST(:fingerprint AS text)
                    ),
                    jsonb_build_object('provider_host_used', false),
                    'ACTIVATION_VERIFIED', 'corr-subscription-security', :now
                )
                """
            ),
            {
                "id": str(uuid4()),
                "service_id": SERVICE_ID,
                "attachment_id": ATTACHMENT_ID,
                "target_id": TARGET_ID,
                "profile_version_id": PROFILE_VERSION_ID,
                "renderer": RENDERER_VERSION,
                "fingerprint": fingerprint,
                "now": now,
            },
        )


def test_postgres_subscription_issue_render_rotate_and_revoke_are_hash_only() -> None:
    admin_engine, factory, schema = _create_schema()
    try:
        _seed(factory)
        issued_at = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
        with factory() as db:
            issued = issue_service_subscription(db, SERVICE_ID, issued_at)
            db.commit()
            assert issued.token is not None
            first_credential = issued.token
            assert len(first_credential) >= 43

            subscription = db.scalar(select(DeliverySubscriptionModel))
            assert subscription is not None
            credential_row = db.scalar(select(DeliverySubscriptionTokenModel))
            assert credential_row is not None
            assert credential_row.token_hash.startswith("sha256:")
            assert first_credential not in credential_row.token_hash
            assert subscription.active_token_hash == credential_row.token_hash

            repeated = issue_service_subscription(
                db, SERVICE_ID, issued_at + timedelta(seconds=1)
            )
            db.commit()
            assert repeated.token is None
            assert (
                db.scalar(select(func.count()).select_from(DeliverySubscriptionTokenModel))
                == 1
            )

            plain = render_public_subscription(
                db,
                first_credential,
                DeliveryOutputFormat.PLAIN_LINKS,
                issued_at + timedelta(minutes=1),
            )
            base64_links = render_public_subscription(
                db,
                first_credential,
                DeliveryOutputFormat.BASE64_LINKS,
                issued_at + timedelta(minutes=1),
            )
            mihomo = render_public_subscription(
                db,
                first_credential,
                DeliveryOutputFormat.MIHOMO,
                issued_at + timedelta(minutes=1),
            )
            sing_box = render_public_subscription(
                db,
                first_credential,
                DeliveryOutputFormat.SING_BOX,
                issued_at + timedelta(minutes=1),
            )
            db.commit()

            assert "edge.example:443" in plain
            assert REMOTE_IDENTITY in plain
            assert "panel" not in plain.lower()
            assert base64.b64decode(base64_links).decode() == plain
            assert "edge.example" in mihomo
            assert "panel" not in mihomo.lower()
            assert json.loads(sing_box)["outbounds"]
            assert "panel" not in sing_box.lower()

            with pytest.raises(DeliveryError) as clash_error:
                render_public_subscription(
                    db,
                    first_credential,
                    DeliveryOutputFormat.CLASH_LEGACY,
                    issued_at + timedelta(minutes=1),
                )
            assert clash_error.value.code in {
                DeliveryErrorCode.DELIVERY_FORMAT_UNSUPPORTED,
                DeliveryErrorCode.DELIVERY_RENDERER_UNSUPPORTED,
                DeliveryErrorCode.SUBSCRIPTION_FORMAT_UNSUPPORTED,
            }
            db.rollback()

            rotated = rotate_service_subscription(
                db, SERVICE_ID, issued_at + timedelta(minutes=2)
            )
            db.commit()
            assert rotated.token is not None
            second_credential = rotated.token
            assert second_credential != first_credential
            assert (
                db.scalar(select(func.count()).select_from(DeliverySubscriptionTokenModel))
                == 2
            )

            assert "edge.example" in render_public_subscription(
                db,
                first_credential,
                DeliveryOutputFormat.PLAIN_LINKS,
                issued_at + timedelta(minutes=3),
            )
            assert "edge.example" in render_public_subscription(
                db,
                second_credential,
                DeliveryOutputFormat.PLAIN_LINKS,
                issued_at + timedelta(minutes=3),
            )
            db.commit()

            with pytest.raises(DeliveryError) as duplicate_rotation:
                rotate_service_subscription(
                    db, SERVICE_ID, issued_at + timedelta(minutes=3)
                )
            assert duplicate_rotation.value.code is DeliveryErrorCode.IDEMPOTENCY_CONFLICT
            db.rollback()

            with pytest.raises(DeliveryError) as expired_old:
                render_public_subscription(
                    db,
                    first_credential,
                    DeliveryOutputFormat.PLAIN_LINKS,
                    issued_at + timedelta(minutes=8),
                )
            assert expired_old.value.code is DeliveryErrorCode.SUBSCRIPTION_EXPIRED
            db.rollback()

            assert "edge.example" in render_public_subscription(
                db,
                second_credential,
                DeliveryOutputFormat.PLAIN_LINKS,
                issued_at + timedelta(minutes=8),
            )
            db.commit()

            revoked = revoke_service_subscription(
                db, SERVICE_ID, issued_at + timedelta(minutes=9)
            )
            db.commit()
            assert revoked.status == "REVOKED"

            repeated_revoke = revoke_service_subscription(
                db, SERVICE_ID, issued_at + timedelta(minutes=10)
            )
            db.commit()
            assert repeated_revoke.status == "REVOKED"

            for credential in (first_credential, second_credential):
                with pytest.raises(DeliveryError):
                    render_public_subscription(
                        db,
                        credential,
                        DeliveryOutputFormat.PLAIN_LINKS,
                        issued_at + timedelta(minutes=10),
                    )
                db.rollback()

            events = list(db.scalars(select(DeliveryAccessEventModel)))
            assert events
            serialized_events = json.dumps(
                [
                    {
                        "actor_type": event.actor_type,
                        "action": event.action,
                        "outcome": event.outcome,
                        "safe_metadata": event.safe_metadata,
                    }
                    for event in events
                ],
                sort_keys=True,
            )
            assert first_credential not in serialized_events
            assert second_credential not in serialized_events
            assert "sha256:" not in serialized_events
            assert "vless://" not in serialized_events
            assert "edge.example" not in serialized_events
    finally:
        _drop_schema(admin_engine, schema)
