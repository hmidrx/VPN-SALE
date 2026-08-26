from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Table, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import platform_api.management as management
from platform_api.catalog_models import ProductVersionModel
from platform_api.database import get_db_session
from platform_api.identity.models import IdentityBase
from platform_api.main import app
from platform_api.management import current_admin
from platform_api.provider_runtime_models import (
    PanelInstanceModel,
    ProviderConnectionTestModel,
    ProviderInboundSnapshotModel,
)
from platform_api.service_models import (
    AllocationPolicyModel,
    AllocationPolicyVersionModel,
    AllocationPoolModel,
    AllocationReservationModel,
    AllocationTargetModel,
    ServiceAttachmentModel,
)

PANEL_ID = "a0000000-0000-4000-8000-000000000001"
PRODUCT_VERSION_ID = "b0000000-0000-4000-8000-000000000001"


@pytest.fixture
def allocation_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, Engine]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(
        engine,
        tables=cast(
            list[Table],
            [
                PanelInstanceModel.__table__,
                ProviderConnectionTestModel.__table__,
                ProviderInboundSnapshotModel.__table__,
                ProductVersionModel.__table__,
                AllocationPolicyModel.__table__,
                AllocationPolicyVersionModel.__table__,
                AllocationPoolModel.__table__,
                AllocationTargetModel.__table__,
                ServiceAttachmentModel.__table__,
                AllocationReservationModel.__table__,
            ],
        ),
    )
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.add(
            PanelInstanceModel(
                id=PANEL_ID,
                public_reference="panel-allocation-test",
                provider_kind="sanaei_3x_ui",
                display_name="Allocation panel",
                endpoint_origin="https://panel.example.invalid",
                base_path="",
                status="ACTIVE",
                tls_policy={},
                endpoint_policy={},
                optimistic_version=1,
                created_at=now,
                updated_at=now,
            )
        )
        db.add(
            ProviderConnectionTestModel(
                id="c0000000-0000-4000-8000-000000000001",
                panel_instance_id=PANEL_ID,
                status="CONTRACT_VERIFIED",
                detected_version="v3.7.0",
                contract_digest="sha256:test-contract-v370",
                latency_ms=4,
                safe_error_code=None,
                tested_at=now,
            )
        )
        for inbound_id in ("101", "102"):
            db.add(
                ProviderInboundSnapshotModel(
                    id=f"4a000000-0000-4000-8000-{int(inbound_id):012d}",
                    panel_instance_id=PANEL_ID,
                    sync_run_id=None,
                    remote_identifier=inbound_id,
                    status="ACTIVE",
                    sanitized_payload={
                        "protocol": "vless",
                        "enabled": True,
                        "remark": f"inbound-{inbound_id}",
                    },
                    observed_at=now,
                )
            )
        db.add(
            ProductVersionModel(
                id=PRODUCT_VERSION_ID,
                product_id="d0000000-0000-4000-8000-000000000001",
                version_number=1,
                status="PUBLISHED",
                product_type="FIXED_PLAN",
                definition_snapshot={},
                options_snapshot={},
                constraints_snapshot=[],
                fulfillment_requirements_snapshot=[],
                created_at=now,
                published_at=now,
                retired_at=None,
            )
        )
        db.commit()

    def database() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    original = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_session] = database
    app.dependency_overrides[current_admin] = lambda: SimpleNamespace(id="admin-allocation")

    def active_permissions(_db: Session, _admin_id: str) -> set[str]:
        return {
            "allocation.read",
            "allocation.manage",
            "allocation.publish",
            "allocation.simulate",
        }

    monkeypatch.setattr(management, "_active_permissions", active_permissions)
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
        engine.dispose()


def test_multi_inbound_policy_lifecycle_and_side_effect_free_simulation(
    allocation_client: tuple[TestClient, Engine],
) -> None:
    client, engine = allocation_client
    pool_response = client.post(
        "/api/v1/admin/allocation/pools",
        json={"name": "دو اینباند اصلی", "status": "ACTIVE"},
    )
    assert pool_response.status_code == 201, pool_response.text
    pool_id = pool_response.json()["id"]

    target_ids: list[str] = []
    for inbound_id in ("101", "102"):
        response = client.post(
            "/api/v1/admin/allocation/targets",
            json={
                "pool_id": pool_id,
                "panel_id": PANEL_ID,
                "inbound_id": inbound_id,
                "provider_kind": "sanaei_3x_ui",
                "required_protocol": "vless",
                "role": "REQUIRED",
                "priority": 10,
                "weight": 100,
                "max_capacity": 1000,
                "safety_reserve": 20,
                "certification_minimum": "v3.7.0",
                "diagnostics": {
                    "healthy": True,
                    "write_mode": "WRITE_ENABLED",
                    "supports_shared_identity": True,
                    "tags": ["premium"],
                },
            },
        )
        assert response.status_code == 201, response.text
        target_ids.append(response.json()["id"])

    policy_response = client.post(
        "/api/v1/admin/allocation/policies", json={"name": "پلن پریمیوم دو ورودی"}
    )
    assert policy_response.status_code == 201, policy_response.text
    policy = policy_response.json()

    version_response = client.post(
        f"/api/v1/admin/allocation/policies/{policy['id']}/versions",
        json={
            "strategy": "ALL_REQUIRED_TARGETS",
            "success_policy": "ALL_REQUIRED",
            "identity_strategy": "SHARED",
            "required_target_count": 2,
            "pool_ids": [pool_id],
            "required_tags": ["premium"],
            "product_version_ids": [PRODUCT_VERSION_ID],
            "plan_references": ["premium_dual"],
            "locations": ["ir"],
            "required_protocols": ["vless"],
        },
    )
    assert version_response.status_code == 201, version_response.text
    version = version_response.json()

    validated = client.post(
        f"/api/v1/admin/allocation/policies/{policy['id']}/versions/{version['id']}/validate",
        json={"expected_policy_version": version["policy_optimistic_version"]},
    )
    assert validated.status_code == 200, validated.text
    published = client.post(
        f"/api/v1/admin/allocation/policies/{policy['id']}/versions/{version['id']}/publish",
        json={"expected_policy_version": validated.json()["policy_optimistic_version"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "PUBLISHED"

    simulation = client.post(
        "/api/v1/admin/allocation/simulate",
        json={
            "product_version_id": PRODUCT_VERSION_ID,
            "plan_reference": "premium_dual",
            "location": "ir",
            "required_attachment_count": 2,
        },
    )
    assert simulation.status_code == 200, simulation.text
    result = simulation.json()
    assert set(result["eligible"]) == set(target_ids)
    assert {item["inbound_id"] for item in result["selected_targets"]} == {"101", "102"}
    assert result["performs_reservation"] is False
    assert result["performs_provider_mutation"] is False
    with Session(engine) as db:
        assert db.query(AllocationReservationModel).count() == 0


def test_allocation_target_requires_synced_certified_inbound(
    allocation_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = allocation_client
    pool_id = client.post(
        "/api/v1/admin/allocation/pools", json={"name": "invalid target test"}
    ).json()["id"]
    response = client.post(
        "/api/v1/admin/allocation/targets",
        json={
            "pool_id": pool_id,
            "panel_id": PANEL_ID,
            "inbound_id": "999",
            "provider_kind": "sanaei_3x_ui",
            "required_protocol": "vless",
            "max_capacity": 10,
            "certification_minimum": "v3.7.0",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ALLOCATION_INBOUND_NOT_SYNCED"


def test_policy_transition_rejects_stale_optimistic_version(
    allocation_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = allocation_client
    policy = client.post(
        "/api/v1/admin/allocation/policies", json={"name": "optimistic policy"}
    ).json()
    updated = client.patch(
        f"/api/v1/admin/allocation/policies/{policy['id']}",
        json={"name": "optimistic policy renamed", "expected_policy_version": 1},
    )
    assert updated.status_code == 200
    stale = client.patch(
        f"/api/v1/admin/allocation/policies/{policy['id']}",
        json={"name": "stale update", "expected_policy_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "CONCURRENT_MODIFICATION"
