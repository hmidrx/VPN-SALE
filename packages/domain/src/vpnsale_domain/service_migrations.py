from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from vpnsale_domain.delivery import DeliveryProfileStatus, DeliveryProfileVersion
from vpnsale_domain.provider_mutations import ProviderOperationStatus, ProviderWriteMode
from vpnsale_domain.services import (
    AllocationReservation,
    AllocationTarget,
    Service,
    ServiceLifecycle,
)


class MigrationErrorCode(StrEnum):
    MIGRATION_NOT_ELIGIBLE = "MIGRATION_NOT_ELIGIBLE"
    MIGRATION_ALREADY_ACTIVE = "MIGRATION_ALREADY_ACTIVE"
    MIGRATION_PLAN_STALE = "MIGRATION_PLAN_STALE"
    MIGRATION_PLAN_EXPIRED = "MIGRATION_PLAN_EXPIRED"
    MIGRATION_APPROVAL_REQUIRED = "MIGRATION_APPROVAL_REQUIRED"
    MIGRATION_SELF_APPROVAL_DENIED = "MIGRATION_SELF_APPROVAL_DENIED"
    MIGRATION_SOURCE_UNCERTAIN = "MIGRATION_SOURCE_UNCERTAIN"
    MIGRATION_SOURCE_CHANGED = "MIGRATION_SOURCE_CHANGED"
    MIGRATION_NO_TARGET = "MIGRATION_NO_TARGET"
    MIGRATION_TARGET_INCOMPATIBLE = "MIGRATION_TARGET_INCOMPATIBLE"
    MIGRATION_TARGET_CAPACITY_UNAVAILABLE = "MIGRATION_TARGET_CAPACITY_UNAVAILABLE"
    MIGRATION_TARGET_WRITE_DISABLED = "MIGRATION_TARGET_WRITE_DISABLED"
    MIGRATION_CREDENTIAL_STRATEGY_UNAVAILABLE = "MIGRATION_CREDENTIAL_STRATEGY_UNAVAILABLE"
    MIGRATION_DELIVERY_PROFILE_INCOMPATIBLE = "MIGRATION_DELIVERY_PROFILE_INCOMPATIBLE"
    MIGRATION_TARGET_PROVISIONING_FAILED = "MIGRATION_TARGET_PROVISIONING_FAILED"
    MIGRATION_TARGET_UNCERTAIN = "MIGRATION_TARGET_UNCERTAIN"
    MIGRATION_CUTOVER_CONFLICT = "MIGRATION_CUTOVER_CONFLICT"
    MIGRATION_CUTOVER_INCOMPLETE = "MIGRATION_CUTOVER_INCOMPLETE"
    MIGRATION_SOURCE_CLEANUP_FAILED = "MIGRATION_SOURCE_CLEANUP_FAILED"
    MIGRATION_ROLLBACK_UNAVAILABLE = "MIGRATION_ROLLBACK_UNAVAILABLE"
    MIGRATION_ROLLBACK_FAILED = "MIGRATION_ROLLBACK_FAILED"
    MIGRATION_PARTIALLY_APPLIED = "MIGRATION_PARTIALLY_APPLIED"
    MIGRATION_RECONCILIATION_REQUIRED = "MIGRATION_RECONCILIATION_REQUIRED"
    MIGRATION_COMPENSATION_REQUIRED = "MIGRATION_COMPENSATION_REQUIRED"
    FAILOVER_APPROVAL_REQUIRED = "FAILOVER_APPROVAL_REQUIRED"
    ORPHAN_REMOTE_IDENTITY_DETECTED = "ORPHAN_REMOTE_IDENTITY_DETECTED"
    PROVIDER_REQUIRES_RECERTIFICATION = "PROVIDER_REQUIRES_RECERTIFICATION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass
class MigrationDomainError(ValueError):
    code: MigrationErrorCode
    safe_message: str


class ServiceMigrationType(StrEnum):
    INBOUND_MOVE = "INBOUND_MOVE"
    NODE_MOVE = "NODE_MOVE"
    PANEL_MOVE = "PANEL_MOVE"
    CROSS_PROVIDER_MOVE = "CROSS_PROVIDER_MOVE"
    ALLOCATION_REPLACEMENT = "ALLOCATION_REPLACEMENT"
    CAPACITY_REBALANCE = "CAPACITY_REBALANCE"
    MAINTENANCE_EVACUATION = "MAINTENANCE_EVACUATION"
    CONTROLLED_FAILOVER = "CONTROLLED_FAILOVER"
    SECURITY_ROTATION_MOVE = "SECURITY_ROTATION_MOVE"
    MANUAL_RECOVERY_MOVE = "MANUAL_RECOVERY_MOVE"


class ServiceMigrationStatus(StrEnum):
    DRAFT = "DRAFT"
    CHECKING_ELIGIBILITY = "CHECKING_ELIGIBILITY"
    SIMULATED = "SIMULATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    RESERVING_TARGET = "RESERVING_TARGET"
    PREPARING_TARGET = "PREPARING_TARGET"
    PROVISIONING_TARGET = "PROVISIONING_TARGET"
    VERIFYING_TARGET = "VERIFYING_TARGET"
    READY_FOR_CUTOVER = "READY_FOR_CUTOVER"
    CUTTING_OVER = "CUTTING_OVER"
    DUAL_ACTIVE_GRACE = "DUAL_ACTIVE_GRACE"
    TARGET_ACTIVE = "TARGET_ACTIVE"
    RETIRING_SOURCE = "RETIRING_SOURCE"
    VERIFYING_SOURCE_RETIREMENT = "VERIFYING_SOURCE_RETIREMENT"
    COMPLETED = "COMPLETED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    RECONCILING = "RECONCILING"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MigrationEligibilityOutcome(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    SOURCE_UNCERTAIN = "SOURCE_UNCERTAIN"
    NO_COMPATIBLE_TARGET = "NO_COMPATIBLE_TARGET"
    TARGET_CAPACITY_UNAVAILABLE = "TARGET_CAPACITY_UNAVAILABLE"
    TARGET_CAPABILITY_MISMATCH = "TARGET_CAPABILITY_MISMATCH"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"
    CONFLICTING_OPERATION = "CONFLICTING_OPERATION"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class ServiceMigrationCredentialStrategy(StrEnum):
    PRESERVE_SHARED_CREDENTIAL = "PRESERVE_SHARED_CREDENTIAL"
    PRESERVE_PER_ATTACHMENT_CREDENTIAL = "PRESERVE_PER_ATTACHMENT_CREDENTIAL"
    ROTATE_SHARED_CREDENTIAL = "ROTATE_SHARED_CREDENTIAL"
    ROTATE_PER_ATTACHMENT_CREDENTIAL = "ROTATE_PER_ATTACHMENT_CREDENTIAL"
    PROVIDER_NATIVE_REISSUE = "PROVIDER_NATIVE_REISSUE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class ServiceMigrationCutoverStrategy(StrEnum):
    COLD = "COLD"
    WARM = "WARM"
    DUAL_ACTIVE_GRACE = "DUAL_ACTIVE_GRACE"
    IN_PLACE_RELATIONSHIP_MOVE = "IN_PLACE_RELATIONSHIP_MOVE"


class ServiceMigrationCleanupStrategy(StrEnum):
    DISABLE_ONLY = "DISABLE_ONLY"
    DETACH_RELATIONSHIP = "DETACH_RELATIONSHIP"
    DELETE_IDENTITY = "DELETE_IDENTITY"
    KEEP_FOR_MANUAL_CLEANUP = "KEEP_FOR_MANUAL_CLEANUP"
    RETIRE_AFTER_GRACE = "RETIRE_AFTER_GRACE"


class MigrationReconciliationOutcome(StrEnum):
    MATCHED = "MATCHED"
    CUTOVER_INCOMPLETE = "CUTOVER_INCOMPLETE"
    SOURCE_STILL_ACTIVE = "SOURCE_STILL_ACTIVE"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_DIFFERENT = "TARGET_DIFFERENT"
    DUPLICATE_REMOTE_IDENTITY = "DUPLICATE_REMOTE_IDENTITY"
    DELIVERY_REVISION_STALE = "DELIVERY_REVISION_STALE"
    CAPACITY_STATE_INCONSISTENT = "CAPACITY_STATE_INCONSISTENT"
    ORPHAN_SOURCE_FOUND = "ORPHAN_SOURCE_FOUND"
    PROVIDER_RECERTIFICATION_REQUIRED = "PROVIDER_RECERTIFICATION_REQUIRED"
    REPAIR_PLAN_REQUIRED = "REPAIR_PLAN_REQUIRED"
    ROLLBACK_AVAILABLE = "ROLLBACK_AVAILABLE"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


@dataclass(frozen=True)
class ServiceMigrationPolicyVersion:
    policy_id: UUID
    version_id: UUID
    version_number: int
    status: str
    allowed_source_provider_kinds: frozenset[str]
    allowed_target_provider_kinds: frozenset[str]
    allowed_protocols: frozenset[str]
    allow_cross_provider: bool
    preserve_credentials_when_supported: bool
    require_rotation_for_security_moves: bool
    allowed_cutover_strategies: frozenset[ServiceMigrationCutoverStrategy]
    allowed_cleanup_strategies: frozenset[ServiceMigrationCleanupStrategy]
    dual_active_grace: timedelta
    source_cleanup_delay: timedelta
    inventory_max_age: timedelta
    required_capabilities: frozenset[str]
    max_migrations_per_service_window: int
    approval_required: bool
    high_risk_approval_required: bool
    rollback_window: timedelta
    published_at: datetime | None = None

    def publish(self, now: datetime) -> ServiceMigrationPolicyVersion:
        if self.status != "VALIDATED" or now.tzinfo is None:
            raise MigrationDomainError(MigrationErrorCode.MIGRATION_NOT_ELIGIBLE, "policy invalid")
        return replace(self, status="PUBLISHED", published_at=now)

    def assert_published(self) -> None:
        if self.status != "PUBLISHED":
            raise MigrationDomainError(
                MigrationErrorCode.MIGRATION_NOT_ELIGIBLE, "policy unpublished"
            )


@dataclass(frozen=True)
class ServiceMigrationRequest:
    request_id: UUID
    service_id: UUID
    migration_type: ServiceMigrationType
    requested_by: UUID
    reason_category: str
    cutover_strategy: ServiceMigrationCutoverStrategy
    cleanup_strategy: ServiceMigrationCleanupStrategy
    credential_rotation_requested: bool = False


@dataclass(frozen=True)
class ServiceMigrationSourceSnapshot:
    snapshot_id: UUID
    service_id: UUID
    attachment_ids: tuple[UUID, ...]
    provider_kinds: tuple[str, ...]
    provider_versions: tuple[str, ...]
    contract_digests: tuple[str, ...]
    remote_identity_references: tuple[str, ...]
    enabled: bool
    traffic_limit_bytes: int | None
    local_lifetime_usage_bytes: int
    observed_remote_usage_bytes: int
    expires_at: datetime | None
    device_limit: int | None
    credential_fingerprints: tuple[str, ...]
    delivery_revision_id: UUID | None
    source_uncertain: bool
    ownership_verified: bool
    captured_at: datetime


@dataclass(frozen=True)
class ServiceMigrationTargetCandidate:
    target: AllocationTarget
    safe_label: str
    protocol: str
    delivery_profile: DeliveryProfileVersion | None
    credential_preservation_supported: bool
    required_capabilities: frozenset[str]
    rejected_reasons: tuple[str, ...] = ()

    def sanitized(self) -> dict[str, str | tuple[str, ...] | bool]:
        return {
            "candidateReference": self.target.target_id.hex[:12],
            "safeLabel": self.safe_label,
            "protocol": self.protocol,
            "credentialPreservationSupported": self.credential_preservation_supported,
            "rejectedReasons": self.rejected_reasons,
        }


@dataclass(frozen=True)
class ServiceMigrationAttachmentPlan:
    attachment_plan_id: UUID
    source_attachment_id: UUID
    target_id: UUID
    protocol: str
    credential_strategy: ServiceMigrationCredentialStrategy
    required: bool
    delivery_profile_version_id: UUID
    target_reservation_id: UUID | None = None
    provider_operation_id: UUID | None = None
    target_verified: bool = False
    cleanup_verified: bool = False


@dataclass(frozen=True)
class ServiceMigrationPlan:
    plan_id: UUID
    migration_type: ServiceMigrationType
    policy_version_id: UUID
    service_id: UUID
    source_snapshot_id: UUID
    attachment_plans: tuple[ServiceMigrationAttachmentPlan, ...]
    cutover_strategy: ServiceMigrationCutoverStrategy
    cleanup_strategy: ServiceMigrationCleanupStrategy
    high_risk: bool
    target_candidate_labels: tuple[str, ...]
    expected_delivery_impact: str
    rollback_feasible: bool
    expires_at: datetime

    def digest(self) -> str:
        parts = [
            self.plan_id.hex,
            self.migration_type.value,
            self.policy_version_id.hex,
            self.service_id.hex,
            self.source_snapshot_id.hex,
            self.cutover_strategy.value,
            self.cleanup_strategy.value,
            str(self.high_risk),
            str(self.rollback_feasible),
            self.expires_at.isoformat(),
        ]
        for item in self.attachment_plans:
            parts.extend(
                [
                    item.source_attachment_id.hex,
                    item.target_id.hex,
                    item.protocol,
                    item.credential_strategy.value,
                    item.delivery_profile_version_id.hex,
                ]
            )
        return "sha256:" + hashlib.sha256("|".join(parts).encode()).hexdigest()


@dataclass(frozen=True)
class ServiceMigrationApproval:
    approval_id: UUID
    migration_id: UUID
    actor_id: UUID
    requester_id: UUID
    plan_digest: str
    high_risk: bool
    approved_at: datetime
    expires_at: datetime

    def assert_valid(self, actor_id: UUID, plan_digest: str, now: datetime) -> None:
        if self.requester_id == actor_id:
            raise MigrationDomainError(
                MigrationErrorCode.MIGRATION_SELF_APPROVAL_DENIED, "self approval denied"
            )
        if self.plan_digest != plan_digest or self.expires_at <= now:
            raise MigrationDomainError(
                MigrationErrorCode.MIGRATION_APPROVAL_REQUIRED, "stale approval"
            )


@dataclass(frozen=True)
class ServiceMigrationStep:
    step_id: UUID
    migration_id: UUID
    name: str
    idempotency_key_digest: str
    status: str
    attempt_count: int = 0


@dataclass(frozen=True)
class ServiceMigrationAttempt:
    attempt_id: UUID
    step_id: UUID
    provider_operation_id: UUID | None
    status: ProviderOperationStatus
    outcome: str
    started_at: datetime
    finished_at: datetime | None = None


@dataclass(frozen=True)
class ServiceMigrationVerification:
    verification_id: UUID
    migration_id: UUID
    attachment_plan_id: UUID
    verified: bool
    checked_at: datetime
    safe_evidence_digest: str


@dataclass(frozen=True)
class ServiceMigrationCutover:
    cutover_id: UUID
    migration_id: UUID
    previous_delivery_revision_id: UUID | None
    new_delivery_revision_id: UUID
    stable_subscription_token_digest: str
    committed_at: datetime


@dataclass(frozen=True)
class ServiceMigrationRollback:
    rollback_id: UUID
    migration_id: UUID
    rollback_type: str
    plan_digest: str
    requested_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True)
class ServiceMigrationReconciliation:
    reconciliation_id: UUID
    migration_id: UUID
    outcome: MigrationReconciliationOutcome
    checked_at: datetime
    requires_approval_for_repair: bool


@dataclass(frozen=True)
class ServiceMigrationCompensation:
    compensation_id: UUID
    migration_id: UUID
    reason_code: MigrationErrorCode
    status: str
    created_at: datetime


@dataclass(frozen=True)
class ServiceMigrationNotification:
    notification_id: UUID
    migration_id: UUID
    template: str
    safe_link_path: str
    outbox_key: str


@dataclass(frozen=True)
class ServiceAllocationReplacement:
    replacement_id: UUID
    migration_id: UUID
    source_target_id: UUID
    target_target_id: UUID
    source_released: bool = False
    target_active: bool = False


@dataclass(frozen=True)
class OrphanedRemoteIdentity:
    orphan_id: UUID
    migration_id: UUID
    service_id: UUID
    source_attachment_id: UUID
    remote_identity_reference_digest: str
    possible_active: bool
    detected_at: datetime
    cleanup_approved: bool = False


@dataclass(frozen=True)
class FailoverProposal:
    proposal_id: UUID
    service_id: UUID
    reason: str
    source_unreachable: bool
    evidence_digest: str
    created_at: datetime
    converted_migration_id: UUID | None = None


@dataclass(frozen=True)
class ServiceMigrationEligibility:
    outcome: MigrationEligibilityOutcome
    reasons: tuple[MigrationErrorCode, ...]
    compatible_candidates: tuple[ServiceMigrationTargetCandidate, ...]

    @property
    def eligible(self) -> bool:
        return self.outcome is MigrationEligibilityOutcome.ELIGIBLE


@dataclass(frozen=True)
class ServiceMigration:
    migration_id: UUID
    migration_reference: str
    service_id: UUID
    service_public_reference: str
    requester_id: UUID
    migration_type: ServiceMigrationType
    status: ServiceMigrationStatus
    policy_version_id: UUID
    plan: ServiceMigrationPlan
    plan_digest: str
    source_snapshot: ServiceMigrationSourceSnapshot
    target_snapshot_id: UUID | None = None
    approval: ServiceMigrationApproval | None = None
    cutover: ServiceMigrationCutover | None = None
    rollback: ServiceMigrationRollback | None = None
    history: tuple[str, ...] = ()
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition(
        self,
        target: ServiceMigrationStatus,
        actor_id: UUID,
        expected_version: int,
        plan_digest: str,
        now: datetime,
        approval: ServiceMigrationApproval | None = None,
    ) -> ServiceMigration:
        if expected_version != self.version:
            raise MigrationDomainError(MigrationErrorCode.CONCURRENT_MODIFICATION, "stale version")
        if plan_digest != self.plan_digest:
            raise MigrationDomainError(MigrationErrorCode.MIGRATION_PLAN_STALE, "plan stale")
        allowed = _allowed_transitions()[self.status]
        if target not in allowed:
            raise MigrationDomainError(MigrationErrorCode.MIGRATION_NOT_ELIGIBLE, "bad transition")
        active_approval = approval or self.approval
        if target in _approval_gated_statuses() and active_approval is None:
            raise MigrationDomainError(
                MigrationErrorCode.MIGRATION_APPROVAL_REQUIRED, "approval required"
            )
        if active_approval is not None and target in _approval_gated_statuses():
            active_approval.assert_valid(actor_id, plan_digest, now)
        if target is ServiceMigrationStatus.READY_FOR_CUTOVER and not all(
            item.target_verified for item in self.plan.attachment_plans if item.required
        ):
            raise MigrationDomainError(
                MigrationErrorCode.MIGRATION_CUTOVER_INCOMPLETE, "target not verified"
            )
        return replace(
            self,
            status=target,
            approval=active_approval,
            history=(*self.history, f"{self.status.value}->{target.value}"),
            version=self.version + 1,
            updated_at=now,
        )


def _allowed_transitions() -> dict[ServiceMigrationStatus, frozenset[ServiceMigrationStatus]]:
    return {
        ServiceMigrationStatus.DRAFT: frozenset(
            {ServiceMigrationStatus.CHECKING_ELIGIBILITY, ServiceMigrationStatus.CANCELLED}
        ),
        ServiceMigrationStatus.CHECKING_ELIGIBILITY: frozenset(
            {
                ServiceMigrationStatus.SIMULATED,
                ServiceMigrationStatus.MANUAL_REVIEW,
                ServiceMigrationStatus.FAILED,
            }
        ),
        ServiceMigrationStatus.SIMULATED: frozenset(
            {
                ServiceMigrationStatus.AWAITING_APPROVAL,
                ServiceMigrationStatus.RESERVING_TARGET,
                ServiceMigrationStatus.CANCELLED,
            }
        ),
        ServiceMigrationStatus.AWAITING_APPROVAL: frozenset(
            {ServiceMigrationStatus.APPROVED, ServiceMigrationStatus.CANCELLED}
        ),
        ServiceMigrationStatus.APPROVED: frozenset(
            {
                ServiceMigrationStatus.RESERVING_TARGET,
                ServiceMigrationStatus.ROLLBACK_PENDING,
                ServiceMigrationStatus.EXPIRED,
            }
        ),
        ServiceMigrationStatus.RESERVING_TARGET: frozenset(
            {
                ServiceMigrationStatus.PREPARING_TARGET,
                ServiceMigrationStatus.FAILED,
                ServiceMigrationStatus.UNCERTAIN,
            }
        ),
        ServiceMigrationStatus.PREPARING_TARGET: frozenset(
            {ServiceMigrationStatus.PROVISIONING_TARGET, ServiceMigrationStatus.ROLLBACK_PENDING}
        ),
        ServiceMigrationStatus.PROVISIONING_TARGET: frozenset(
            {
                ServiceMigrationStatus.VERIFYING_TARGET,
                ServiceMigrationStatus.PARTIALLY_APPLIED,
                ServiceMigrationStatus.UNCERTAIN,
            }
        ),
        ServiceMigrationStatus.VERIFYING_TARGET: frozenset(
            {ServiceMigrationStatus.READY_FOR_CUTOVER, ServiceMigrationStatus.MANUAL_REVIEW}
        ),
        ServiceMigrationStatus.READY_FOR_CUTOVER: frozenset(
            {ServiceMigrationStatus.CUTTING_OVER, ServiceMigrationStatus.ROLLBACK_PENDING}
        ),
        ServiceMigrationStatus.CUTTING_OVER: frozenset(
            {
                ServiceMigrationStatus.DUAL_ACTIVE_GRACE,
                ServiceMigrationStatus.TARGET_ACTIVE,
                ServiceMigrationStatus.UNCERTAIN,
            }
        ),
        ServiceMigrationStatus.DUAL_ACTIVE_GRACE: frozenset(
            {ServiceMigrationStatus.RETIRING_SOURCE, ServiceMigrationStatus.ROLLBACK_PENDING}
        ),
        ServiceMigrationStatus.TARGET_ACTIVE: frozenset(
            {ServiceMigrationStatus.RETIRING_SOURCE, ServiceMigrationStatus.ROLLBACK_PENDING}
        ),
        ServiceMigrationStatus.RETIRING_SOURCE: frozenset(
            {
                ServiceMigrationStatus.VERIFYING_SOURCE_RETIREMENT,
                ServiceMigrationStatus.MANUAL_REVIEW,
            }
        ),
        ServiceMigrationStatus.VERIFYING_SOURCE_RETIREMENT: frozenset(
            {ServiceMigrationStatus.COMPLETED, ServiceMigrationStatus.MANUAL_REVIEW}
        ),
        ServiceMigrationStatus.ROLLBACK_PENDING: frozenset(
            {ServiceMigrationStatus.ROLLING_BACK, ServiceMigrationStatus.MANUAL_REVIEW}
        ),
        ServiceMigrationStatus.ROLLING_BACK: frozenset(
            {ServiceMigrationStatus.ROLLED_BACK, ServiceMigrationStatus.MANUAL_REVIEW}
        ),
        ServiceMigrationStatus.RECONCILING: frozenset(
            {
                ServiceMigrationStatus.COMPLETED,
                ServiceMigrationStatus.COMPENSATION_REQUIRED,
                ServiceMigrationStatus.MANUAL_REVIEW,
            }
        ),
        ServiceMigrationStatus.COMPENSATION_REQUIRED: frozenset(
            {ServiceMigrationStatus.MANUAL_REVIEW}
        ),
        ServiceMigrationStatus.PARTIALLY_APPLIED: frozenset(
            {ServiceMigrationStatus.RECONCILING, ServiceMigrationStatus.ROLLBACK_PENDING}
        ),
        ServiceMigrationStatus.UNCERTAIN: frozenset(
            {ServiceMigrationStatus.RECONCILING, ServiceMigrationStatus.MANUAL_REVIEW}
        ),
        ServiceMigrationStatus.FAILED: frozenset({ServiceMigrationStatus.RECONCILING}),
        ServiceMigrationStatus.MANUAL_REVIEW: frozenset(
            {ServiceMigrationStatus.RECONCILING, ServiceMigrationStatus.ROLLBACK_PENDING}
        ),
        ServiceMigrationStatus.COMPLETED: frozenset(),
        ServiceMigrationStatus.ROLLED_BACK: frozenset(),
        ServiceMigrationStatus.CANCELLED: frozenset(),
        ServiceMigrationStatus.EXPIRED: frozenset(),
    }


def _approval_gated_statuses() -> frozenset[ServiceMigrationStatus]:
    return frozenset(
        {
            ServiceMigrationStatus.APPROVED,
            ServiceMigrationStatus.RESERVING_TARGET,
            ServiceMigrationStatus.CUTTING_OVER,
            ServiceMigrationStatus.RETIRING_SOURCE,
            ServiceMigrationStatus.ROLLING_BACK,
        }
    )


def capture_source_snapshot(
    service: Service,
    now: datetime,
    local_lifetime_usage_bytes: int,
    observed_remote_usage_bytes: int,
    delivery_revision_id: UUID | None,
    source_uncertain: bool = False,
) -> ServiceMigrationSourceSnapshot:
    if now.tzinfo is None:
        raise MigrationDomainError(MigrationErrorCode.MIGRATION_NOT_ELIGIBLE, "timestamp naive")
    return ServiceMigrationSourceSnapshot(
        uuid4(),
        service.service_id,
        tuple(item.attachment_id for item in service.attachments),
        tuple(item.target.provider_kind for item in service.attachments),
        tuple(item.target.provider_version for item in service.attachments),
        tuple(item.target.contract_digest for item in service.attachments),
        tuple(item.remote_identity_reference or "UNVERIFIED" for item in service.attachments),
        service.lifecycle is ServiceLifecycle.ACTIVE,
        service.entitlement.traffic_limit_bytes,
        local_lifetime_usage_bytes,
        observed_remote_usage_bytes,
        service.entitlement.expires_at,
        service.entitlement.device_limit,
        tuple(item.credential_fingerprint or "sha256:unverified" for item in service.attachments),
        delivery_revision_id,
        source_uncertain,
        all(item.remote_identity_reference is not None for item in service.attachments),
        now,
    )


def evaluate_eligibility(
    service: Service,
    request: ServiceMigrationRequest,
    policy: ServiceMigrationPolicyVersion,
    candidates: tuple[ServiceMigrationTargetCandidate, ...],
    active_migration_exists: bool,
    conflicting_operation_exists: bool,
    now: datetime,
) -> ServiceMigrationEligibility:
    policy.assert_published()
    reasons: list[MigrationErrorCode] = []
    if active_migration_exists:
        reasons.append(MigrationErrorCode.MIGRATION_ALREADY_ACTIVE)
    if conflicting_operation_exists:
        return ServiceMigrationEligibility(
            MigrationEligibilityOutcome.CONFLICTING_OPERATION,
            (MigrationErrorCode.MIGRATION_ALREADY_ACTIVE,),
            (),
        )
    if service.lifecycle not in {ServiceLifecycle.ACTIVE, ServiceLifecycle.DEGRADED}:
        reasons.append(MigrationErrorCode.MIGRATION_NOT_ELIGIBLE)
    if request.cutover_strategy not in policy.allowed_cutover_strategies:
        reasons.append(MigrationErrorCode.MIGRATION_NOT_ELIGIBLE)
    compatible = tuple(candidate for candidate in candidates if not candidate.rejected_reasons)
    if not compatible:
        return ServiceMigrationEligibility(
            MigrationEligibilityOutcome.NO_COMPATIBLE_TARGET,
            (*reasons, MigrationErrorCode.MIGRATION_NO_TARGET),
            (),
        )
    for candidate in compatible:
        if candidate.target.write_mode is ProviderWriteMode.RECERTIFICATION_REQUIRED:
            return ServiceMigrationEligibility(
                MigrationEligibilityOutcome.RECERTIFICATION_REQUIRED,
                (MigrationErrorCode.PROVIDER_REQUIRES_RECERTIFICATION,),
                (),
            )
        if candidate.target.write_mode is not ProviderWriteMode.WRITE_ENABLED:
            reasons.append(MigrationErrorCode.MIGRATION_TARGET_WRITE_DISABLED)
        try:
            if candidate.target.available_capacity(now) <= 0:
                reasons.append(MigrationErrorCode.MIGRATION_TARGET_CAPACITY_UNAVAILABLE)
        except Exception:
            reasons.append(MigrationErrorCode.MIGRATION_TARGET_CAPACITY_UNAVAILABLE)
        if (
            candidate.delivery_profile is None
            or candidate.delivery_profile.status is not DeliveryProfileStatus.PUBLISHED
        ):
            reasons.append(MigrationErrorCode.MIGRATION_DELIVERY_PROFILE_INCOMPATIBLE)
        if not policy.required_capabilities.issubset(candidate.required_capabilities):
            reasons.append(MigrationErrorCode.MIGRATION_TARGET_INCOMPATIBLE)
    if reasons:
        outcome = (
            MigrationEligibilityOutcome.TARGET_CAPACITY_UNAVAILABLE
            if MigrationErrorCode.MIGRATION_TARGET_CAPACITY_UNAVAILABLE in reasons
            else MigrationEligibilityOutcome.INELIGIBLE
        )
        return ServiceMigrationEligibility(outcome, tuple(dict.fromkeys(reasons)), compatible)
    return ServiceMigrationEligibility(MigrationEligibilityOutcome.ELIGIBLE, (), compatible)


def choose_credential_strategy(
    source_protocol: str,
    target_protocol: str,
    candidate: ServiceMigrationTargetCandidate,
    request: ServiceMigrationRequest,
    policy: ServiceMigrationPolicyVersion,
    shared_identity: bool,
) -> ServiceMigrationCredentialStrategy:
    if (
        request.migration_type is ServiceMigrationType.SECURITY_ROTATION_MOVE
        or request.credential_rotation_requested
    ):
        return (
            ServiceMigrationCredentialStrategy.ROTATE_SHARED_CREDENTIAL
            if shared_identity
            else ServiceMigrationCredentialStrategy.ROTATE_PER_ATTACHMENT_CREDENTIAL
        )
    if (
        source_protocol == target_protocol
        and candidate.credential_preservation_supported
        and policy.preserve_credentials_when_supported
    ):
        return (
            ServiceMigrationCredentialStrategy.PRESERVE_SHARED_CREDENTIAL
            if shared_identity
            else ServiceMigrationCredentialStrategy.PRESERVE_PER_ATTACHMENT_CREDENTIAL
        )
    if source_protocol != target_protocol:
        return (
            ServiceMigrationCredentialStrategy.ROTATE_SHARED_CREDENTIAL
            if shared_identity
            else ServiceMigrationCredentialStrategy.ROTATE_PER_ATTACHMENT_CREDENTIAL
        )
    return ServiceMigrationCredentialStrategy.PROVIDER_NATIVE_REISSUE


def simulate_migration_plan(
    service: Service,
    request: ServiceMigrationRequest,
    policy: ServiceMigrationPolicyVersion,
    source_snapshot: ServiceMigrationSourceSnapshot,
    candidates: tuple[ServiceMigrationTargetCandidate, ...],
    now: datetime,
) -> ServiceMigrationPlan:
    eligibility = evaluate_eligibility(service, request, policy, candidates, False, False, now)
    if not eligibility.eligible:
        raise MigrationDomainError(
            MigrationErrorCode.MIGRATION_NOT_ELIGIBLE, eligibility.outcome.value
        )
    selected = tuple(
        sorted(
            eligibility.compatible_candidates,
            key=lambda item: (item.target.priority, item.safe_label, item.target.target_id.hex),
        )
    )[: service.entitlement.required_attachment_count]
    if len(selected) < service.entitlement.required_attachment_count:
        raise MigrationDomainError(MigrationErrorCode.MIGRATION_NO_TARGET, "not enough targets")
    source_attachments = service.attachments[: len(selected)]
    attachment_plans: list[ServiceMigrationAttachmentPlan] = []
    source_protocol = (
        service.entitlement.protocol_eligibility[0]
        if service.entitlement.protocol_eligibility
        else selected[0].protocol
    )
    for source_attachment, candidate in zip(source_attachments, selected, strict=True):
        if candidate.delivery_profile is None:
            raise MigrationDomainError(
                MigrationErrorCode.MIGRATION_DELIVERY_PROFILE_INCOMPATIBLE, "missing profile"
            )
        strategy = choose_credential_strategy(
            source_protocol, candidate.protocol, candidate, request, policy, True
        )
        attachment_plans.append(
            ServiceMigrationAttachmentPlan(
                uuid4(),
                source_attachment.attachment_id,
                candidate.target.target_id,
                candidate.protocol,
                strategy,
                source_attachment.required,
                candidate.delivery_profile.version_id,
            )
        )
    high_risk = (
        request.migration_type
        in {ServiceMigrationType.CROSS_PROVIDER_MOVE, ServiceMigrationType.CONTROLLED_FAILOVER}
        or request.cutover_strategy is ServiceMigrationCutoverStrategy.COLD
    )
    return ServiceMigrationPlan(
        uuid4(),
        request.migration_type,
        policy.version_id,
        service.service_id,
        source_snapshot.snapshot_id,
        tuple(attachment_plans),
        request.cutover_strategy,
        request.cleanup_strategy,
        high_risk,
        tuple(item.safe_label for item in selected),
        "stable subscription token; content changes only after verified cutover",
        not source_snapshot.source_uncertain,
        now + policy.rollback_window,
    )


def reserve_target_capacity(
    plan: ServiceMigrationPlan,
    service_id: UUID,
    now: datetime,
    lease: timedelta,
) -> tuple[AllocationReservation, ...]:
    if now.tzinfo is None:
        raise MigrationDomainError(MigrationErrorCode.MIGRATION_NOT_ELIGIBLE, "timestamp naive")
    return tuple(
        AllocationReservation(uuid4(), service_id, item.target_id, "ACTIVE", now, now + lease)
        for item in plan.attachment_plans
    )


def attach_reservations(
    plan: ServiceMigrationPlan, reservations: tuple[AllocationReservation, ...]
) -> ServiceMigrationPlan:
    by_target = {item.target_id: item.reservation_id for item in reservations}
    return replace(
        plan,
        attachment_plans=tuple(
            replace(item, target_reservation_id=by_target[item.target_id])
            for item in plan.attachment_plans
        ),
    )


def mark_target_verified(
    plan: ServiceMigrationPlan,
    attachment_plan_id: UUID,
    provider_operation_id: UUID,
) -> ServiceMigrationPlan:
    return replace(
        plan,
        attachment_plans=tuple(
            replace(item, provider_operation_id=provider_operation_id, target_verified=True)
            if item.attachment_plan_id == attachment_plan_id
            else item
            for item in plan.attachment_plans
        ),
    )


def commit_cutover(
    migration: ServiceMigration,
    actor_id: UUID,
    expected_version: int,
    new_delivery_revision_id: UUID,
    stable_subscription_token: str,
    now: datetime,
) -> ServiceMigration:
    if migration.status not in {
        ServiceMigrationStatus.READY_FOR_CUTOVER,
        ServiceMigrationStatus.CUTTING_OVER,
    }:
        raise MigrationDomainError(MigrationErrorCode.MIGRATION_CUTOVER_CONFLICT, "not ready")
    if not all(item.target_verified for item in migration.plan.attachment_plans if item.required):
        raise MigrationDomainError(
            MigrationErrorCode.MIGRATION_CUTOVER_INCOMPLETE, "target not verified"
        )
    transitioned = migration.transition(
        ServiceMigrationStatus.CUTTING_OVER, actor_id, expected_version, migration.plan_digest, now
    )
    token_digest = hmac.new(
        b"subscription-token-redaction", stable_subscription_token.encode(), hashlib.sha256
    ).hexdigest()
    cutover = ServiceMigrationCutover(
        uuid4(),
        migration.migration_id,
        migration.source_snapshot.delivery_revision_id,
        new_delivery_revision_id,
        "sha256:" + token_digest,
        now,
    )
    target_status = (
        ServiceMigrationStatus.DUAL_ACTIVE_GRACE
        if migration.plan.cutover_strategy
        in {ServiceMigrationCutoverStrategy.WARM, ServiceMigrationCutoverStrategy.DUAL_ACTIVE_GRACE}
        else ServiceMigrationStatus.TARGET_ACTIVE
    )
    return replace(
        transitioned,
        status=target_status,
        cutover=cutover,
        history=(*transitioned.history, f"CUTOVER:{new_delivery_revision_id.hex}"),
        version=transitioned.version + 1,
        updated_at=now,
    )


def retire_source(
    migration: ServiceMigration,
    actor_id: UUID,
    expected_version: int,
    now: datetime,
    ownership_verified: bool,
    shared_remote_identity_active: bool,
) -> ServiceMigration:
    if migration.status not in {
        ServiceMigrationStatus.DUAL_ACTIVE_GRACE,
        ServiceMigrationStatus.TARGET_ACTIVE,
        ServiceMigrationStatus.RETIRING_SOURCE,
    }:
        raise MigrationDomainError(MigrationErrorCode.MIGRATION_SOURCE_CLEANUP_FAILED, "not ready")
    if migration.plan.cleanup_strategy is ServiceMigrationCleanupStrategy.DELETE_IDENTITY and (
        not ownership_verified or shared_remote_identity_active
    ):
        raise MigrationDomainError(
            MigrationErrorCode.MIGRATION_SOURCE_CLEANUP_FAILED, "destructive cleanup blocked"
        )
    retiring = migration.transition(
        ServiceMigrationStatus.RETIRING_SOURCE,
        actor_id,
        expected_version,
        migration.plan_digest,
        now,
    )
    verifying = retiring.transition(
        ServiceMigrationStatus.VERIFYING_SOURCE_RETIREMENT,
        actor_id,
        retiring.version,
        migration.plan_digest,
        now,
    )
    return verifying.transition(
        ServiceMigrationStatus.COMPLETED, actor_id, verifying.version, migration.plan_digest, now
    )


def request_rollback(
    migration: ServiceMigration,
    actor_id: UUID,
    expected_version: int,
    now: datetime,
    source_available: bool,
    newer_service_operation: bool,
) -> ServiceMigration:
    if (
        migration.plan.expires_at <= now
        or newer_service_operation
        or (migration.cutover is not None and not source_available)
    ):
        raise MigrationDomainError(
            MigrationErrorCode.MIGRATION_ROLLBACK_UNAVAILABLE, "rollback unsafe"
        )
    pending = migration.transition(
        ServiceMigrationStatus.ROLLBACK_PENDING,
        actor_id,
        expected_version,
        migration.plan_digest,
        now,
    )
    rollback = ServiceMigrationRollback(
        uuid4(),
        migration.migration_id,
        "PRE_CUTOVER" if migration.cutover is None else "POST_CUTOVER",
        migration.plan_digest,
        now,
    )
    return replace(pending, rollback=rollback)


def reconcile_migration(
    migration: ServiceMigration,
    source_enabled: bool,
    target_present: bool,
    delivery_revision_id: UUID | None,
    source_capacity_released: bool,
) -> ServiceMigrationReconciliation:
    outcome = MigrationReconciliationOutcome.MATCHED
    if not target_present:
        outcome = MigrationReconciliationOutcome.TARGET_MISSING
    elif migration.cutover and delivery_revision_id != migration.cutover.new_delivery_revision_id:
        outcome = MigrationReconciliationOutcome.DELIVERY_REVISION_STALE
    elif migration.status is ServiceMigrationStatus.COMPLETED and source_enabled:
        outcome = MigrationReconciliationOutcome.SOURCE_STILL_ACTIVE
    elif source_capacity_released and migration.status is not ServiceMigrationStatus.COMPLETED:
        outcome = MigrationReconciliationOutcome.CAPACITY_STATE_INCONSISTENT
    return ServiceMigrationReconciliation(
        uuid4(),
        migration.migration_id,
        outcome,
        datetime.now(UTC),
        outcome is not MigrationReconciliationOutcome.MATCHED,
    )


def create_migration(
    service: Service,
    request: ServiceMigrationRequest,
    policy: ServiceMigrationPolicyVersion,
    source_snapshot: ServiceMigrationSourceSnapshot,
    plan: ServiceMigrationPlan,
    now: datetime,
) -> ServiceMigration:
    digest = plan.digest()
    reference_seed = (
        hashlib.sha256(f"{service.public_reference}:{plan.plan_id}".encode())
        .hexdigest()[:12]
        .upper()
    )
    return ServiceMigration(
        uuid4(),
        f"MIG-{reference_seed}",
        service.service_id,
        service.public_reference,
        request.requested_by,
        request.migration_type,
        ServiceMigrationStatus.SIMULATED,
        policy.version_id,
        plan,
        digest,
        source_snapshot,
        created_at=now,
        updated_at=now,
    )
