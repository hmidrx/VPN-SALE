from __future__ import annotations

import base64
from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from panel_adapters.contracts import EndpointValidator
from panel_adapters.sanaei_3x_ui_v370 import Sanaei3xUiV370InboundOption
from sqlalchemy import Engine, Table, create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import platform_api.management as management
import platform_api.providers as providers
from platform_api.database import get_db_session
from platform_api.identity.models import AuditLogModel, IdentityBase
from platform_api.main import app
from platform_api.management import current_admin
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
    ProviderInboundSnapshotModel,
    ProviderSyncRunModel,
)


@pytest.fixture
def provider_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Engine]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    IdentityBase.metadata.create_all(
        engine,
        tables=cast(
            list[Table],
            [
                PanelInstanceModel.__table__,
                PanelCredentialModel.__table__,
                ProviderConnectionTestModel.__table__,
                ProviderSyncRunModel.__table__,
                ProviderInboundSnapshotModel.__table__,
                AuditLogModel.__table__,
            ],
        ),
    )

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
    app.dependency_overrides[current_admin] = lambda: SimpleNamespace(id="admin-test")

    def active_permissions(_db: Session, _admin_id: str) -> set[str]:
        return {
            "providers.read",
            "providers.manage",
            "providers.manage_credentials",
            "providers.read_diagnostics",
            "providers.read_inventory",
            "providers.test_connection",
            "providers.sync",
        }

    def validate_endpoint(_self: object, _raw: object, _endpoint: object, _tls: object) -> str:
        return "https://panel.example.invalid:443"

    monkeypatch.setattr(management, "_active_permissions", active_permissions)
    monkeypatch.setattr(EndpointValidator, "validate", validate_endpoint)
    monkeypatch.setenv(
        "PROVIDER_VAULT_MASTER_KEY_B64", base64.urlsafe_b64encode(b"k" * 32).decode()
    )
    monkeypatch.setenv("PROVIDER_VAULT_KEY_VERSION", "aead-test")
    try:
        yield TestClient(app), engine
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
        engine.dispose()


def test_panel_crud_and_write_only_credential(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, engine = provider_client
    created = client.post(
        "/api/v1/admin/providers/panels",
        json={
            "display_name": "پنل اصلی",
            "provider_kind": "sanaei_3x_ui",
            "provider_version": "v3.7.0",
            "endpoint_origin": "https://panel.example.invalid",
            "base_path": "/tenant",
        },
    )
    assert created.status_code == 201, created.text
    panel = created.json()
    reference = panel["public_reference"]
    assert panel["provider_version"] == "v3.7.0"
    assert panel["base_path"] == "/tenant"
    assert panel["credential"] == {
        "configured": False,
        "credential_kind": None,
        "key_version": None,
        "updated_at": None,
    }

    secret = "inert-test-bearer-token"  # noqa: S105 -- nonfunctional fixture value
    stored = client.put(
        f"/api/v1/admin/providers/panels/{reference}/credential",
        json={"auth_mode": "bearer_token", "bearer_token": secret},
    )
    assert stored.status_code == 200, stored.text
    assert secret not in stored.text
    assert stored.json()["credential_kind"] == "bearer_token"

    detail = client.get(f"/api/v1/admin/providers/panels/{reference}")
    assert detail.status_code == 200
    assert secret not in detail.text
    assert detail.json()["credential"]["configured"] is True
    assert detail.json()["status"] == "RECERTIFICATION_REQUIRED"

    capabilities = client.get(f"/api/v1/admin/providers/panels/{reference}/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["provider_version"] == "v3.7.0"
    assert capabilities.json()["writes_enabled_by_default"] is False

    with Session(engine) as db:
        encrypted = db.scalar(select(PanelCredentialModel))
        assert encrypted is not None
        assert secret not in encrypted.ciphertext_b64


def test_panel_update_uses_optimistic_version(
    provider_client: tuple[TestClient, Engine],
) -> None:
    client, _engine = provider_client
    created = client.post(
        "/api/v1/admin/providers/panels",
        json={
            "display_name": "پنل دوم",
            "endpoint_origin": "https://panel.example.invalid",
        },
    ).json()
    reference = created["public_reference"]
    updated = client.patch(
        f"/api/v1/admin/providers/panels/{reference}",
        json={"optimistic_version": 1, "display_name": "پنل دوم جدید"},
    )
    assert updated.status_code == 200
    assert updated.json()["optimistic_version"] == 2
    conflict = client.patch(
        f"/api/v1/admin/providers/panels/{reference}",
        json={"optimistic_version": 1, "display_name": "نام کهنه"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "CONCURRENT_MODIFICATION"


def test_connection_and_inventory_sync_persist_sanitized_evidence(
    provider_client: tuple[TestClient, Engine], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, engine = provider_client
    created = client.post(
        "/api/v1/admin/providers/panels",
        json={
            "display_name": "پنل همگام‌سازی",
            "endpoint_origin": "https://panel.example.invalid",
        },
    ).json()
    reference = created["public_reference"]

    class FakeTransport:
        async def aclose(self) -> None:
            pass

    class FakeClient:
        async def server_status(self) -> dict[str, object]:
            return {"panelVersion": "v3.7.0"}

        async def list_inbound_options(self) -> tuple[Sanaei3xUiV370InboundOption, ...]:
            return (
                Sanaei3xUiV370InboundOption(
                    inbound_id=101,
                    remark="ورودی اصلی",
                    tag="in-main",
                    protocol="vless",
                    port=443,
                    enabled=True,
                    node_id=None,
                    tls_flow_capable=True,
                ),
            )

    async def live_client(
        _db: Session, _row: PanelInstanceModel
    ) -> tuple[FakeTransport, FakeClient]:
        return FakeTransport(), FakeClient()

    monkeypatch.setattr(providers, "_live_client", live_client)
    tested = client.post(f"/api/v1/admin/providers/panels/{reference}/test-connection")
    assert tested.status_code == 200
    assert tested.json()["status"] == "CONTRACT_VERIFIED"
    synced = client.post(f"/api/v1/admin/providers/panels/{reference}/sync")
    assert synced.status_code == 200
    assert synced.json()["status"] == "SUCCESS"
    assert synced.json()["inbound_count"] == 1

    inventory = client.get(f"/api/v1/admin/providers/panels/{reference}/inbounds")
    assert inventory.status_code == 200
    assert inventory.json()[0]["remote_identifier"] == "101"
    assert inventory.json()[0]["sanitized_payload"] == {
        "remark": "ورودی اصلی",
        "tag": "in-main",
        "protocol": "vless",
        "port": 443,
        "enabled": True,
        "node_id": None,
        "tls_flow_capable": True,
    }
    with Session(engine) as db:
        row = db.scalar(select(PanelInstanceModel))
        assert row is not None and row.status == "ACTIVE"


def test_provider_routes_fail_closed_without_admin_database() -> None:
    original = dict(app.dependency_overrides)
    app.dependency_overrides.pop(current_admin, None)

    app.dependency_overrides[get_db_session] = lambda: object()
    try:
        response = TestClient(app).get("/api/v1/admin/providers/panels")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
