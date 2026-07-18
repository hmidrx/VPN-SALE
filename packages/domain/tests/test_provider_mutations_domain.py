from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from vpnsale_domain.provider_mutations import (
    ProtocolCredentialFactory,
    ProviderMutationExecutor,
    ProviderMutationOutcome,
    ProviderObservedRemoteIdentity,
    ProviderOperation,
    ProviderOperationStatus,
    ProviderReconciler,
    ProviderWriteEnablement,
    ProviderWriteError,
    ProviderWriteErrorCode,
    ProviderWriteMode,
)
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelReference,
    ProviderCapability,
    ProviderKind,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)


class MemoryEncryptor:
    def encrypt_credential(self, plaintext: str, credential_kind: str) -> str:
        assert credential_kind
        return "vault://sealed/" + str(len(plaintext))


class FakeAdapter:
    endpoint_identifier = "sanaei.clients.update"

    def __init__(
        self,
        before: ProviderObservedRemoteIdentity | None,
        after: ProviderObservedRemoteIdentity | None,
        outcome: ProviderMutationOutcome,
    ) -> None:
        self.before = before
        self.after = after
        self.outcome = outcome
        self.sent = 0

    def read_identity(self, operation: ProviderOperation) -> ProviderObservedRemoteIdentity | None:
        assert operation.operation_id
        return self.after if self.sent else self.before

    def mutate_once(self, operation: ProviderOperation) -> ProviderMutationOutcome:
        assert operation.status is ProviderOperationStatus.EXECUTING
        self.sent += 1
        return self.outcome


def desired(enabled: bool = True) -> DesiredRemoteIdentity:
    return DesiredRemoteIdentity(
        "svc-1",
        "vless",
        enabled,
        RemoteTrafficLimit(1024, False),
        RemoteExpiryPolicy(datetime(2026, 8, 1, tzinfo=UTC), False),
        2,
        "safe customer",
        "vpn-sale-ms6-a2b",
        (RemoteIdentifier("inbound-1"),),
        "sha256:fingerprint",
        "sha256:options",
    )


def observed(
    state: DesiredRemoteIdentity, digest: str = "sha256:before"
) -> ProviderObservedRemoteIdentity:
    return ProviderObservedRemoteIdentity(RemoteIdentifier("client-1"), digest, state)


def operation(
    state: DesiredRemoteIdentity, expected: str | None = "sha256:before"
) -> ProviderOperation:
    return ProviderOperation(
        uuid4(),
        PanelReference("panel-1"),
        ProviderKind.SANAEI_3X_UI,
        ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
        ProviderCapability.CLIENT_UPDATE,
        state,
        expected,
        "sha256:plan",
        datetime.now(UTC) + timedelta(minutes=10),
        "panel-1:update:svc-1",
        "sha256:request",
    )


def enabled() -> ProviderWriteEnablement:
    requested = ProviderWriteEnablement(
        PanelReference("panel-1"), ProviderKind.SANAEI_3X_UI, ProviderWriteMode.CANARY_ONLY
    ).request("operator-a", "sha256:report")
    return requested.approve(
        "operator-b",
        "v3.5.0",
        "sha256:contract",
        frozenset({ProviderCapability.CLIENT_UPDATE}),
        timedelta(days=7),
    )


def test_credential_generation_is_random_fingerprinted_and_sealed_without_plaintext() -> None:
    factory = ProtocolCredentialFactory()
    first = factory.generate("trojan_password")
    second = factory.generate("trojan_password")
    assert first.plaintext != second.plaintext
    assert first.fingerprint.value != second.fingerprint.value
    sealed = factory.seal(first, MemoryEncryptor())
    assert first.plaintext not in repr(sealed)
    assert sealed.encrypted_reference.startswith("vault://sealed/")
    with pytest.raises(ProviderWriteError) as exc:
        factory.generate("wireguard_peer")
    assert exc.value.code is ProviderWriteErrorCode.PROVIDER_OPERATION_NOT_SUPPORTED


def test_enablement_requires_separate_approver_and_exact_material() -> None:
    pending = ProviderWriteEnablement(
        PanelReference("panel-1"), ProviderKind.SANAEI_3X_UI, ProviderWriteMode.CANARY_ONLY
    ).request("operator-a", "sha256:report")
    with pytest.raises(ProviderWriteError) as exc:
        pending.approve("operator-a", "v3.5.0", "sha256:contract", frozenset(), timedelta(days=1))
    assert exc.value.code is ProviderWriteErrorCode.PROVIDER_WRITE_SELF_APPROVAL_DENIED
    approved = pending.approve(
        "operator-b",
        "v3.5.0",
        "sha256:contract",
        frozenset({ProviderCapability.CLIENT_UPDATE}),
        timedelta(days=1),
    )
    approved.assert_can_execute(
        ProviderCapability.CLIENT_UPDATE, "v3.5.0", "sha256:contract", datetime.now(UTC)
    )
    with pytest.raises(ProviderWriteError) as changed:
        approved.assert_can_execute(
            ProviderCapability.CLIENT_UPDATE, "v3.5.1", "sha256:contract", datetime.now(UTC)
        )
    assert changed.value.code is ProviderWriteErrorCode.PROVIDER_REQUIRES_RECERTIFICATION


def test_executor_requires_read_before_write_and_postconditions() -> None:
    state = desired(False)
    adapter = FakeAdapter(
        observed(desired(True)), observed(state), ProviderMutationOutcome.COMMITTED_AND_VERIFIED
    )
    result = ProviderMutationExecutor().execute(
        operation(state), enabled(), adapter, "v3.5.0", "sha256:contract", "sha256:plan"
    )
    assert result.operation.status is ProviderOperationStatus.SUCCEEDED
    assert adapter.sent == 1
    failing = FakeAdapter(
        observed(desired(True), "sha256:changed"),
        observed(state),
        ProviderMutationOutcome.COMMITTED_AND_VERIFIED,
    )
    with pytest.raises(ProviderWriteError) as exc:
        ProviderMutationExecutor().execute(
            operation(state), enabled(), failing, "v3.5.0", "sha256:contract", "sha256:plan"
        )
    assert exc.value.code is ProviderWriteErrorCode.PROVIDER_REMOTE_STATE_STALE
    assert failing.sent == 0


def test_http_success_without_matching_postconditions_fails() -> None:
    state = desired(False)
    adapter = FakeAdapter(
        observed(desired(True)),
        observed(desired(True)),
        ProviderMutationOutcome.COMMITTED_AND_VERIFIED,
    )
    result = ProviderMutationExecutor().execute(
        operation(state), enabled(), adapter, "v3.5.0", "sha256:contract", "sha256:plan"
    )
    assert result.operation.status is ProviderOperationStatus.FAILED
    assert result.outcome is ProviderMutationOutcome.CONTRACT_VIOLATION


def test_ambiguous_result_reconciles_without_second_send() -> None:
    state = desired(False)
    adapter = FakeAdapter(
        observed(desired(True)),
        observed(state),
        ProviderMutationOutcome.COMMITTED_BUT_RESPONSE_LOST,
    )
    result = ProviderMutationExecutor().execute(
        operation(state), enabled(), adapter, "v3.5.0", "sha256:contract", "sha256:plan"
    )
    assert result.operation.status is ProviderOperationStatus.SUCCEEDED
    assert adapter.sent == 1
    uncertain = FakeAdapter(
        observed(desired(True)),
        observed(desired(True)),
        ProviderMutationOutcome.UNKNOWN_COMMIT_STATE,
    )
    uncertain_result = ProviderMutationExecutor().execute(
        operation(state), enabled(), uncertain, "v3.5.0", "sha256:contract", "sha256:plan"
    )
    assert uncertain_result.operation.status is ProviderOperationStatus.UNCERTAIN
    issue = ProviderReconciler().reconcile(uncertain_result.operation, observed(desired(True)))
    assert issue.destructive_repair_requires_approval is True
