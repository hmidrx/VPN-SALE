"""Production write-safety domain model for provider mutations.

The module is transport and framework agnostic.  It models the durable operation
rules that SQL repositories, workers and exact provider adapters must enforce.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelReference,
    ProviderCapability,
    ProviderKind,
    ProviderMutationOperation,
    RemoteIdentifier,
)


class ProviderWriteMode(StrEnum):
    READ_ONLY = "READ_ONLY"
    CANARY_ONLY = "CANARY_ONLY"
    WRITE_PENDING_APPROVAL = "WRITE_PENDING_APPROVAL"
    WRITE_ENABLED = "WRITE_ENABLED"
    WRITE_SUSPENDED = "WRITE_SUSPENDED"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"


class ProviderOperationStatus(StrEnum):
    PLANNED = "PLANNED"
    PREFLIGHTING = "PREFLIGHTING"
    BLOCKED = "BLOCKED"
    READY = "READY"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    RECONCILING = "RECONCILING"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"


class ProviderMutationOutcome(StrEnum):
    NOT_SENT = "NOT_SENT"
    REJECTED = "REJECTED"
    CONFIRMED_NO_CHANGE = "CONFIRMED_NO_CHANGE"
    COMMITTED_AND_VERIFIED = "COMMITTED_AND_VERIFIED"
    COMMITTED_BUT_RESPONSE_LOST = "COMMITTED_BUT_RESPONSE_LOST"
    UNKNOWN_COMMIT_STATE = "UNKNOWN_COMMIT_STATE"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"


class ProviderReconciliationOutcome(StrEnum):
    MATCHED = "MATCHED"
    REMOTE_MISSING = "REMOTE_MISSING"
    REMOTE_EXTRA = "REMOTE_EXTRA"
    REMOTE_DIFFERENT = "REMOTE_DIFFERENT"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    DUPLICATE_REMOTE_IDENTITY = "DUPLICATE_REMOTE_IDENTITY"
    WAITING_FOR_EVENTUAL_CONSISTENCY = "WAITING_FOR_EVENTUAL_CONSISTENCY"
    REPAIR_PLAN_REQUIRED = "REPAIR_PLAN_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class ProviderWriteErrorCode(StrEnum):
    PROVIDER_WRITE_DISABLED = "PROVIDER_WRITE_DISABLED"
    PROVIDER_WRITE_CERTIFICATION_REQUIRED = "PROVIDER_WRITE_CERTIFICATION_REQUIRED"
    PROVIDER_WRITE_CERTIFICATION_EXPIRED = "PROVIDER_WRITE_CERTIFICATION_EXPIRED"
    PROVIDER_WRITE_CERTIFICATION_INVALID = "PROVIDER_WRITE_CERTIFICATION_INVALID"
    PROVIDER_WRITE_APPROVAL_REQUIRED = "PROVIDER_WRITE_APPROVAL_REQUIRED"
    PROVIDER_WRITE_SELF_APPROVAL_DENIED = "PROVIDER_WRITE_SELF_APPROVAL_DENIED"
    PROVIDER_OPERATION_NOT_SUPPORTED = "PROVIDER_OPERATION_NOT_SUPPORTED"
    PROVIDER_OPERATION_CONFLICT = "PROVIDER_OPERATION_CONFLICT"
    PROVIDER_OPERATION_ALREADY_COMPLETED = "PROVIDER_OPERATION_ALREADY_COMPLETED"
    PROVIDER_OPERATION_UNCERTAIN = "PROVIDER_OPERATION_UNCERTAIN"
    PROVIDER_REMOTE_STATE_STALE = "PROVIDER_REMOTE_STATE_STALE"
    PROVIDER_POSTCONDITION_FAILED = "PROVIDER_POSTCONDITION_FAILED"
    PROVIDER_PARTIAL_MUTATION = "PROVIDER_PARTIAL_MUTATION"
    PROVIDER_RECONCILIATION_REQUIRED = "PROVIDER_RECONCILIATION_REQUIRED"
    PROVIDER_COMPENSATION_REQUIRED = "PROVIDER_COMPENSATION_REQUIRED"
    PROVIDER_CANARY_SCOPE_INVALID = "PROVIDER_CANARY_SCOPE_INVALID"
    PROVIDER_CANARY_CLEANUP_FAILED = "PROVIDER_CANARY_CLEANUP_FAILED"
    PROVIDER_UNRELATED_RESOURCE_CHANGED = "PROVIDER_UNRELATED_RESOURCE_CHANGED"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_CONTRACT_MISMATCH = "PROVIDER_CONTRACT_MISMATCH"
    PROVIDER_REQUIRES_RECERTIFICATION = "PROVIDER_REQUIRES_RECERTIFICATION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class ProviderWriteError(Exception):
    code: ProviderWriteErrorCode
    safe_message: str


@dataclass(frozen=True)
class ProviderCredentialFingerprint:
    algorithm: str
    value: str
    version: int


@dataclass(frozen=True)
class ProviderCredentialMaterial:
    material_id: UUID
    credential_kind: str
    encrypted_reference: str
    fingerprint: ProviderCredentialFingerprint
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    supersedes_material_id: UUID | None = None


@dataclass(frozen=True)
class PlainProviderCredential:
    credential_kind: str
    plaintext: str
    fingerprint: ProviderCredentialFingerprint


class CredentialEncryptor(Protocol):
    def encrypt_credential(self, plaintext: str, credential_kind: str) -> str: ...


class ProtocolCredentialFactory:
    def generate(self, credential_kind: str, version: int = 1) -> PlainProviderCredential:
        if credential_kind in {"vless_uuid", "vmess_uuid"}:
            plaintext = str(uuid4())
        elif credential_kind == "trojan_password":
            plaintext = secrets.token_urlsafe(32)
        elif credential_kind == "shadowsocks_password":
            alphabet = string.ascii_letters + string.digits + "-_"
            plaintext = "".join(secrets.choice(alphabet) for _ in range(32))
        else:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_OPERATION_NOT_SUPPORTED,
                "credential kind is not certified for writes",
            )
        digest = hmac.new(b"provider-credential-fingerprint", plaintext.encode(), hashlib.sha256)
        return PlainProviderCredential(
            credential_kind,
            plaintext,
            ProviderCredentialFingerprint("hmac-sha256", "sha256:" + digest.hexdigest(), version),
        )

    def seal(
        self, credential: PlainProviderCredential, encryptor: CredentialEncryptor
    ) -> ProviderCredentialMaterial:
        encrypted_reference = encryptor.encrypt_credential(
            credential.plaintext, credential.credential_kind
        )
        return ProviderCredentialMaterial(
            uuid4(), credential.credential_kind, encrypted_reference, credential.fingerprint
        )


@dataclass(frozen=True)
class ProviderWriteEnablement:
    panel_reference: PanelReference
    provider_kind: ProviderKind
    mode: ProviderWriteMode = ProviderWriteMode.READ_ONLY
    version: str | None = None
    contract_digest: str | None = None
    canary_report_digest: str | None = None
    approved_capabilities: frozenset[ProviderCapability] = frozenset()
    requested_by: str | None = None
    approved_by: str | None = None
    expires_at: datetime | None = None
    optimistic_version: int = 1

    def assert_can_execute(
        self,
        capability: ProviderCapability,
        detected_version: str,
        detected_digest: str,
        now: datetime,
    ) -> None:
        if self.mode is not ProviderWriteMode.WRITE_ENABLED:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_WRITE_DISABLED, "writes disabled"
            )
        if self.expires_at is None or self.expires_at <= now:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_WRITE_CERTIFICATION_EXPIRED,
                "write certification expired",
            )
        if self.version != detected_version or self.contract_digest != detected_digest:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_REQUIRES_RECERTIFICATION,
                "panel material changed after approval",
            )
        if capability not in self.approved_capabilities:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_OPERATION_NOT_SUPPORTED,
                "capability not approved for this panel",
            )

    def request(self, requester: str, report_digest: str) -> ProviderWriteEnablement:
        if self.mode not in {ProviderWriteMode.CANARY_ONLY, ProviderWriteMode.WRITE_SUSPENDED}:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_WRITE_CERTIFICATION_REQUIRED,
                "valid canary certificate required",
            )
        return replace(
            self,
            mode=ProviderWriteMode.WRITE_PENDING_APPROVAL,
            requested_by=requester,
            canary_report_digest=report_digest,
            optimistic_version=self.optimistic_version + 1,
        )

    def approve(
        self,
        approver: str,
        version: str,
        contract_digest: str,
        capabilities: frozenset[ProviderCapability],
        ttl: timedelta,
    ) -> ProviderWriteEnablement:
        if approver == self.requested_by:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_WRITE_SELF_APPROVAL_DENIED,
                "requester cannot approve provider writes",
            )
        if self.mode is not ProviderWriteMode.WRITE_PENDING_APPROVAL:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_WRITE_APPROVAL_REQUIRED,
                "write enablement is not pending approval",
            )
        return replace(
            self,
            mode=ProviderWriteMode.WRITE_ENABLED,
            approved_by=approver,
            version=version,
            contract_digest=contract_digest,
            approved_capabilities=capabilities,
            expires_at=datetime.now(UTC) + ttl,
            optimistic_version=self.optimistic_version + 1,
        )

    def revoke(self) -> ProviderWriteEnablement:
        return replace(
            self,
            mode=ProviderWriteMode.WRITE_SUSPENDED,
            optimistic_version=self.optimistic_version + 1,
        )


@dataclass(frozen=True)
class ProviderObservedRemoteIdentity:
    remote_identity: RemoteIdentifier
    snapshot_digest: str
    state: DesiredRemoteIdentity | None
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ProviderOperationAttempt:
    attempt_id: UUID
    status_before_transport: ProviderOperationStatus
    sanitized_endpoint_identifier: str
    sent_at: datetime


@dataclass(frozen=True)
class ProviderOperationVerification:
    verification_id: UUID
    outcome: ProviderMutationOutcome
    observed: ProviderObservedRemoteIdentity | None
    verified_at: datetime
    safe_reason: str


@dataclass(frozen=True)
class ProviderOperation:
    operation_id: UUID
    panel_reference: PanelReference
    provider_kind: ProviderKind
    operation: ProviderMutationOperation
    capability: ProviderCapability
    desired_state: DesiredRemoteIdentity
    expected_snapshot_digest: str | None
    plan_digest: str
    plan_expires_at: datetime
    idempotency_scope: str
    request_digest: str
    status: ProviderOperationStatus = ProviderOperationStatus.PLANNED
    attempts: tuple[ProviderOperationAttempt, ...] = ()
    verifications: tuple[ProviderOperationVerification, ...] = ()

    def ensure_plan_current(self, supplied_digest: str, now: datetime) -> None:
        if self.plan_digest != supplied_digest:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_CONTRACT_MISMATCH, "plan digest mismatch"
            )
        if self.plan_expires_at <= now:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_REMOTE_STATE_STALE, "operation plan expired"
            )
        if self.status is ProviderOperationStatus.SUCCEEDED:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_OPERATION_ALREADY_COMPLETED,
                "operation already completed",
            )
        if self.status is ProviderOperationStatus.UNCERTAIN:
            raise ProviderWriteError(
                ProviderWriteErrorCode.PROVIDER_OPERATION_UNCERTAIN,
                "uncertain operation requires reconciliation before retry",
            )


@dataclass(frozen=True)
class ProviderMutationResult:
    operation: ProviderOperation
    outcome: ProviderMutationOutcome


class ProviderMutationAdapter(Protocol):
    endpoint_identifier: str

    def read_identity(
        self, operation: ProviderOperation
    ) -> ProviderObservedRemoteIdentity | None: ...

    def mutate_once(self, operation: ProviderOperation) -> ProviderMutationOutcome: ...


class ProviderMutationExecutor:
    def execute(
        self,
        operation: ProviderOperation,
        enablement: ProviderWriteEnablement,
        adapter: ProviderMutationAdapter,
        detected_version: str,
        detected_digest: str,
        supplied_plan_digest: str,
    ) -> ProviderMutationResult:
        now = datetime.now(UTC)
        operation.ensure_plan_current(supplied_plan_digest, now)
        enablement.assert_can_execute(operation.capability, detected_version, detected_digest, now)
        before = adapter.read_identity(operation)
        if operation.expected_snapshot_digest is not None:
            if before is None or before.snapshot_digest != operation.expected_snapshot_digest:
                raise ProviderWriteError(
                    ProviderWriteErrorCode.PROVIDER_REMOTE_STATE_STALE,
                    "remote state changed before mutation",
                )
        attempt = ProviderOperationAttempt(
            uuid4(), ProviderOperationStatus.EXECUTING, adapter.endpoint_identifier, now
        )
        executing = replace(
            operation,
            status=ProviderOperationStatus.EXECUTING,
            attempts=operation.attempts + (attempt,),
        )
        outcome = adapter.mutate_once(executing)
        observed = adapter.read_identity(executing)
        if outcome in {
            ProviderMutationOutcome.UNKNOWN_COMMIT_STATE,
            ProviderMutationOutcome.COMMITTED_BUT_RESPONSE_LOST,
        }:
            if observed is not None and observed.state == operation.desired_state:
                outcome = ProviderMutationOutcome.COMMITTED_AND_VERIFIED
            else:
                verification = ProviderOperationVerification(
                    uuid4(),
                    outcome,
                    observed,
                    datetime.now(UTC),
                    "ambiguous outcome requires reconciliation",
                )
                return ProviderMutationResult(
                    replace(
                        executing,
                        status=ProviderOperationStatus.UNCERTAIN,
                        verifications=executing.verifications + (verification,),
                    ),
                    outcome,
                )
        if observed is None or observed.state != operation.desired_state:
            verification = ProviderOperationVerification(
                uuid4(),
                ProviderMutationOutcome.CONTRACT_VIOLATION,
                observed,
                datetime.now(UTC),
                "postcondition failed",
            )
            return ProviderMutationResult(
                replace(
                    executing,
                    status=ProviderOperationStatus.FAILED,
                    verifications=executing.verifications + (verification,),
                ),
                ProviderMutationOutcome.CONTRACT_VIOLATION,
            )
        verification = ProviderOperationVerification(
            uuid4(),
            ProviderMutationOutcome.COMMITTED_AND_VERIFIED,
            observed,
            datetime.now(UTC),
            "postconditions verified",
        )
        return ProviderMutationResult(
            replace(
                executing,
                status=ProviderOperationStatus.SUCCEEDED,
                verifications=executing.verifications + (verification,),
            ),
            ProviderMutationOutcome.COMMITTED_AND_VERIFIED,
        )


@dataclass(frozen=True)
class ProviderReconciliationIssue:
    issue_id: UUID
    operation_id: UUID
    outcome: ProviderReconciliationOutcome
    safe_summary: str
    destructive_repair_requires_approval: bool


class ProviderReconciler:
    def reconcile(
        self, operation: ProviderOperation, observed: ProviderObservedRemoteIdentity | None
    ) -> ProviderReconciliationIssue:
        if observed is None:
            outcome = ProviderReconciliationOutcome.REMOTE_MISSING
        elif observed.state == operation.desired_state:
            outcome = ProviderReconciliationOutcome.MATCHED
        else:
            outcome = ProviderReconciliationOutcome.REMOTE_DIFFERENT
        return ProviderReconciliationIssue(
            uuid4(),
            operation.operation_id,
            outcome,
            "sanitized reconciliation outcome",
            outcome is not ProviderReconciliationOutcome.MATCHED,
        )
