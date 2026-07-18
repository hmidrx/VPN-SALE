from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from panel_adapters.contracts import CERTIFIED_CONTRACTS
from panel_adapters.write_contracts import (
    build_dry_run_plan,
    execute_provider_mutation_disabled,
    preflight_mutation,
    provider_write_contracts,
)
from vpnsale_domain.providers import (
    CapabilitySupport,
    DesiredRemoteIdentity,
    MutationPreflightStatus,
    PanelCredentialReference,
    PanelInstance,
    PanelReference,
    ProviderCertificationStatus,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    ProviderWriteState,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)


def _desired(
    inbounds: tuple[RemoteIdentifier, ...] = (RemoteIdentifier("inbound-1"),),
) -> DesiredRemoteIdentity:
    return DesiredRemoteIdentity(
        "shop-id-1",
        "vless",
        True,
        RemoteTrafficLimit(1_000_000, False),
        RemoteExpiryPolicy(datetime(2026, 8, 1, tzinfo=UTC), False),
        2,
        "customer safe",
        "vpn-sale safe label",
        inbounds,
        "fp:credential",
        "sha256:options",
    )


def _panel(kind: ProviderKind) -> PanelInstance:
    return PanelInstance(
        uuid4(),
        PanelReference("panel-safe"),
        kind,
        "safe",
        "https://panel.invalid",
        "",
        "enabled",
        PanelCredentialReference(uuid4(), True, "session", "v1"),
    )


def _command(operation: ProviderMutationOperation, kind: ProviderKind) -> ProviderMutationCommand:
    contract = CERTIFIED_CONTRACTS[kind]
    return ProviderMutationCommand(
        UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        operation,
        "svc_1",
        "cus_1",
        PanelReference("panel-safe"),
        contract.contract_digest,
        contract.release_tag,
        RemoteIdentifier("remote-safe")
        if operation is not ProviderMutationOperation.CREATE_REMOTE_IDENTITY
        else None,
        (RemoteIdentifier("inbound-1"),),
        _desired(),
        None if operation is ProviderMutationOperation.CREATE_REMOTE_IDENTITY else "sha256:old",
        f"panel-safe:{operation.value}:svc_1",
        "admin_1",
        "milestone test",
        datetime(2026, 7, 18, tzinfo=UTC),
        "corr_1",
        None,
    )


def test_pasarguard_target_is_corrected_and_v510_absent() -> None:
    contracts = provider_write_contracts()
    pg = CERTIFIED_CONTRACTS[ProviderKind.PASARGUARD]
    assert pg.release_tag == "v4.0.2"
    assert pg.commit_sha.startswith("0b0ddaa")
    assert contracts[ProviderKind.PASARGUARD].target_tag == "v4.0.2"
    warning = contracts[ProviderKind.PASARGUARD].correction_warning
    assert warning is not None
    assert "API-key" in warning


def test_write_contracts_are_provider_specific() -> None:
    contracts = provider_write_contracts()
    assert (
        contracts[ProviderKind.SANAEI_3X_UI].write_state
        is ProviderWriteState.LIVE_WRITE_CANARY_REQUIRED
    )
    sanaei_names = {op.request_dto for op in contracts[ProviderKind.SANAEI_3X_UI].operations}
    alireza_names = {op.request_dto for op in contracts[ProviderKind.ALIREZA_X_UI].operations}
    pasar_names = {op.request_dto for op in contracts[ProviderKind.PASARGUARD].operations}
    assert all(name.startswith("Sanaei") for name in sanaei_names)
    assert all(name.startswith("Alireza") for name in alireza_names)
    assert all(name.startswith("PasarGuard") for name in pasar_names)


def test_preflight_ready_sends_no_transport_and_dry_run_is_sanitized() -> None:
    kind = ProviderKind.SANAEI_3X_UI
    panel = _panel(kind)
    command = _command(ProviderMutationOperation.CREATE_REMOTE_IDENTITY, kind)
    result = preflight_mutation(
        panel,
        kind,
        command,
        "3.5.0",
        CERTIFIED_CONTRACTS[kind].contract_digest,
        ProviderCertificationStatus.CONTRACT_VERIFIED,
    )
    assert result.status is MutationPreflightStatus.READY
    plan = build_dry_run_plan(kind, panel, command)
    rendered = repr(plan).lower()
    assert plan.sanitized_endpoint_identifier == "sanaei.clients.add"
    assert "raw_payload" not in rendered
    assert "cookie" not in rendered
    assert "password" not in rendered
    assert "https://panel.invalid" not in rendered
    assert plan.plan_digest.startswith("sha256:")
    assert plan.capability_evidence[0].support is CapabilitySupport.SUPPORTED


def test_unsupported_operation_fails_before_transport() -> None:
    kind = ProviderKind.ALIREZA_X_UI
    result = preflight_mutation(
        _panel(kind),
        kind,
        _command(ProviderMutationOperation.ATTACH_REMOTE_INBOUND, kind),
        "1.11.3",
        CERTIFIED_CONTRACTS[kind].contract_digest,
        ProviderCertificationStatus.CONTRACT_VERIFIED,
    )
    assert result.status is MutationPreflightStatus.UNSUPPORTED


def test_contract_mismatch_and_stale_snapshot_fail_closed() -> None:
    kind = ProviderKind.PASARGUARD
    mismatch = preflight_mutation(
        _panel(kind),
        kind,
        _command(ProviderMutationOperation.CREATE_REMOTE_IDENTITY, kind),
        "4.0.2",
        "sha256:old",
        ProviderCertificationStatus.CONTRACT_VERIFIED,
    )
    assert mismatch.status is MutationPreflightStatus.CONTRACT_MISMATCH
    stale = preflight_mutation(
        _panel(kind),
        kind,
        replace(
            _command(ProviderMutationOperation.UPDATE_REMOTE_IDENTITY, kind),
            expected_remote_snapshot=None,
        ),
        "4.0.2",
        None,
        ProviderCertificationStatus.CONTRACT_VERIFIED,
    )
    assert stale.status is MutationPreflightStatus.STALE_REMOTE_STATE


def test_unlimited_zero_and_timezone_are_explicit() -> None:
    assert RemoteTrafficLimit(None, True).unlimited is True
    assert RemoteTrafficLimit(0, False).bytes_limit == 0
    with pytest.raises(ValueError):
        RemoteTrafficLimit(None, False)
    with pytest.raises(ValueError):
        RemoteExpiryPolicy(datetime(2026, 8, 1), False)


def test_production_execution_remains_disabled() -> None:
    assert execute_provider_mutation_disabled() == "PROVIDER_WRITE_NOT_ENABLED"
