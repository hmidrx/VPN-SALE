from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from panel_adapters.contracts import CERTIFIED_CONTRACTS
from panel_adapters.write_execution import SanaeiAuthenticatedTransport
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from vpnsale_domain.providers import ProviderKind

from platform_api import catalog_models, wallet_models
from platform_api.fulfillment_runtime_models import FulfillmentTargetBindingModel
from platform_api.identity.models import IdentityBase
from platform_api.order_models import OrderItemModel, OrderModel, TransactionalOutboxModel
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
)
from platform_api.service_models import (
    AllocationPoolModel,
    AllocationTargetModel,
    ServiceFulfillmentRequestModel,
    ServiceModel,
)
from platform_worker.order_fulfillment import EVENT_TYPE, OrderFulfillmentWorker
from platform_worker.real_provisioner import DatabaseSanaeiProvisioner

PRODUCT_ID = "1a111111-1111-4111-8111-111111111111"
PRODUCT_VERSION_ID = "2a222222-2222-4222-8222-222222222222"
PANEL_ID = "3a333333-3333-4333-8333-333333333333"
CREDENTIAL_ID = "4a444444-4444-4444-8444-444444444444"
CONNECTION_TEST_ID = "5a555555-5555-4555-8555-555555555555"
CUSTOMER_ID = "6a666666-6666-4666-8666-666666666666"
QUOTE_ID = "7a777777-7777-4777-8777-777777777777"


def _factory() -> sessionmaker[Session]:
    _ = catalog_models, wallet_models
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed(factory: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    with factory.begin() as db:
        pool = AllocationPoolModel(name="provider-safe", status="ACTIVE", created_at=now)
        db.add(pool)
        db.flush()
        target = AllocationTargetModel(
            pool_id=pool.id,
            panel_id=PANEL_ID,
            node_id=None,
            inbound_id="1",
            provider_kind=ProviderKind.SANAEI_3X_UI.value,
            required_protocol="vless",
            role="PRIMARY",
            priority=1,
            weight=1,
            max_capacity=100,
            safety_reserve=10,
            status="ACTIVE",
            certification_minimum="CONTRACT_VERIFIED",
            safe_diagnostics={},
        )
        db.add(target)
        db.flush()
        db.add(
            FulfillmentTargetBindingModel(
                product_version_id=PRODUCT_VERSION_ID,
                location_code="de",
                quality_code="standard",
                allocation_target_id=target.id,
                capability_codes=["limit.traffic"],
                active=True,
                created_at=now,
            )
        )
        db.add(
            PanelInstanceModel(
                id=PANEL_ID,
                public_reference="panel_safe",
                provider_kind=ProviderKind.SANAEI_3X_UI.value,
                display_name="safe",
                endpoint_origin="https://panel.invalid",
                base_path="",
                status="enabled",
                tls_policy={"verify_tls": True},
                endpoint_policy={"allowed_ports": [443], "require_https": True},
                optimistic_version=1,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            PanelCredentialModel(
                id=CREDENTIAL_ID,
                panel_instance_id=PANEL_ID,
                credential_kind="session",
                key_version="aead-v1",
                nonce_b64="AAAAAAAAAAAAAAAA",
                ciphertext_b64="AAAAAAAAAAAAAAAAAAAAAA==",
                created_at=now,
            )
        )
        db.add(
            ProviderConnectionTestModel(
                id=CONNECTION_TEST_ID,
                panel_instance_id=PANEL_ID,
                status="CONTRACT_VERIFIED",
                detected_version="3.5.0",
                contract_digest=contract.contract_digest,
                latency_ms=1,
                safe_error_code=None,
                tested_at=now,
            )
        )
        order = OrderModel(
            reference="ord_vault_blocked",
            customer_id=CUSTOMER_ID,
            quote_id=QUOTE_ID,
            quote_reference="quote_vault_blocked",
            status="READY_FOR_FULFILLMENT",
            financial_status="PAID",
            fulfillment_status="READY",
            payment_method="WALLET",
            currency="IRR",
            subtotal_rial=1_000_000,
            adjustment_total_rial=0,
            final_amount_rial=1_000_000,
            snapshot={},
            created_at=now,
            paid_at=now,
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
                "selected_options": {
                    "location_code": "de",
                    "quality_code": "standard",
                    "duration_days": 30,
                    "traffic_bytes": 50 * 1024**3,
                    "device_count": 1,
                },
                "fulfillment_requirement_snapshot": [{"capability_code": "limit.traffic"}],
            },
            position=1,
        )
        db.add(item)
        db.flush()
        db.add(
            TransactionalOutboxModel(
                event_key="vault-blocked-event",
                event_type=EVENT_TYPE,
                status="PENDING",
                payload={"order_id": order.id, "correlation_id": "corr-vault"},
                attempt_count=0,
                available_at=now - timedelta(seconds=1),
                claimed_at=None,
                processed_at=None,
                failure_category=None,
                created_at=now,
            )
        )


@pytest.mark.parametrize("invalid_key", [None, "not-a-valid-32-byte-key"])
def test_missing_or_invalid_vault_key_blocks_releases_lease_and_performs_zero_http(
    monkeypatch: pytest.MonkeyPatch, invalid_key: str | None
) -> None:
    factory = _factory()
    _seed(factory)
    if invalid_key is None:
        monkeypatch.delenv("PROVIDER_VAULT_MASTER_KEY_B64", raising=False)
    else:
        monkeypatch.setenv("PROVIDER_VAULT_MASTER_KEY_B64", invalid_key)

    calls = 0

    async def forbidden_authentication(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        raise AssertionError("provider HTTP authentication must not run")

    monkeypatch.setattr(SanaeiAuthenticatedTransport, "authenticate", forbidden_authentication)
    worker = OrderFulfillmentWorker(
        factory,
        DatabaseSanaeiProvisioner(factory, writes_enabled=True),
        "vault-test-worker",
    )

    assert worker.run_once() == 1
    assert calls == 0
    with factory() as db:
        attempt = db.scalar(select(ServiceFulfillmentRequestModel))
        event = db.scalar(select(TransactionalOutboxModel))
        assert attempt is not None
        assert event is not None
        assert attempt.status == "BLOCKED"
        assert attempt.failure_category == "BLOCKED_BY_CONFIGURATION"
        assert attempt.lease_owner is None
        assert attempt.lease_expires_at is None
        assert attempt.next_attempt_at is not None
        assert event.status == "PENDING"
        assert event.claimed_at is None
        assert event.failure_category == "BLOCKED_BY_CONFIGURATION"
        assert db.scalar(select(func.count()).select_from(ServiceModel)) == 0
