from __future__ import annotations

import hmac
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4

from .quality import GateState, ReleaseCandidate


class ProductionReleaseError(ValueError):
    pass


class ProductionReleaseStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    CHANGE_FREEZE = "CHANGE_FREEZE"
    BACKUP_PENDING = "BACKUP_PENDING"
    BACKUP_VERIFIED = "BACKUP_VERIFIED"
    DEPLOYMENT_PENDING = "DEPLOYMENT_PENDING"
    DEPLOYING = "DEPLOYING"
    VERIFYING_DEPLOYMENT = "VERIFYING_DEPLOYMENT"
    CANARY_PENDING = "CANARY_PENDING"
    CANARY_RUNNING = "CANARY_RUNNING"
    CANARY_PAUSED = "CANARY_PAUSED"
    CANARY_FAILED = "CANARY_FAILED"
    PROGRESSIVE_ROLLOUT = "PROGRESSIVE_ROLLOUT"
    ROLLOUT_PAUSED = "ROLLOUT_PAUSED"
    ROLLOUT_FAILED = "ROLLOUT_FAILED"
    FULL_EXPOSURE_PENDING = "FULL_EXPOSURE_PENDING"
    HYPERCARE = "HYPERCARE"
    COMPLETED = "COMPLETED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    PARTIALLY_ROLLED_BACK = "PARTIALLY_ROLLED_BACK"
    INCIDENT_ACTIVE = "INCIDENT_ACTIVE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ApprovalRole(StrEnum):
    REQUESTER = "REQUESTER"
    RELEASE_APPROVER = "RELEASE_APPROVER"
    DEPLOYMENT_APPROVER = "DEPLOYMENT_APPROVER"
    SECURITY_APPROVER = "SECURITY_APPROVER"
    ROLLBACK_APPROVER = "ROLLBACK_APPROVER"


class PhaseType(StrEnum):
    DEPLOYMENT_SMOKE = "DEPLOYMENT_SMOKE"
    SYNTHETIC_INTERNAL = "SYNTHETIC_INTERNAL"
    STAFF_INTERNAL = "STAFF_INTERNAL"
    PROVIDER_CANARY = "PROVIDER_CANARY"
    ALLOWLISTED_CUSTOMER = "ALLOWLISTED_CUSTOMER"
    LOW_PERCENTAGE = "LOW_PERCENTAGE"
    MEDIUM_PERCENTAGE = "MEDIUM_PERCENTAGE"
    HIGH_PERCENTAGE = "HIGH_PERCENTAGE"
    FULL_EXPOSURE = "FULL_EXPOSURE"


class CohortBasis(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    STAFF = "STAFF"
    ALLOWLISTED_CUSTOMER = "ALLOWLISTED_CUSTOMER"
    ALLOWLISTED_RESELLER = "ALLOWLISTED_RESELLER"
    DETERMINISTIC_PERCENTAGE = "DETERMINISTIC_PERCENTAGE"


class RollbackType(StrEnum):
    FEATURE_EXPOSURE_ROLLBACK = "FEATURE_EXPOSURE_ROLLBACK"
    CONFIGURATION_RELEASE_ROLLBACK = "CONFIGURATION_RELEASE_ROLLBACK"
    APPLICATION_ARTIFACT_ROLLBACK = "APPLICATION_ARTIFACT_ROLLBACK"
    COHORT_DISABLE = "COHORT_DISABLE"
    PROVIDER_WRITE_SUSPENSION = "PROVIDER_WRITE_SUSPENSION"
    NEW_PROVISIONING_PAUSE = "NEW_PROVISIONING_PAUSE"
    FORWARD_FIX_REQUIRED = "FORWARD_FIX_REQUIRED"
    CUSTOMER_SERVICE_REPAIR = "CUSTOMER_SERVICE_REPAIR"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ReconciliationOutcome(StrEnum):
    MATCHED = "MATCHED"
    RELEASE_DRIFT = "RELEASE_DRIFT"
    ARTIFACT_MISMATCH = "ARTIFACT_MISMATCH"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    FINANCIAL_REVIEW_REQUIRED = "FINANCIAL_REVIEW_REQUIRED"
    PROVIDER_RECONCILIATION_REQUIRED = "PROVIDER_RECONCILIATION_REQUIRED"
    SERVICE_REPAIR_REQUIRED = "SERVICE_REPAIR_REQUIRED"
    DELIVERY_REPAIR_REQUIRED = "DELIVERY_REPAIR_REQUIRED"
    INCIDENT_REVIEW_REQUIRED = "INCIDENT_REVIEW_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class FinalDecision(StrEnum):
    ROLLED_BACK = "ROLLED_BACK"
    PARTIALLY_DEPLOYED = "PARTIALLY_DEPLOYED"
    HYPERCARE_REQUIRED = "HYPERCARE_REQUIRED"
    COMPLETED_WITH_LIMITATIONS = "COMPLETED_WITH_LIMITATIONS"
    CONTROLLED_ROLLOUT_COMPLETED = "CONTROLLED_ROLLOUT_COMPLETED"


class ProviderCertificationResult(StrEnum):
    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    PASSED_WITH_UNSUPPORTED_STEPS = "PASSED_WITH_UNSUPPORTED_STEPS"
    FAILED = "FAILED"
    CLEANUP_FAILED = "CLEANUP_FAILED"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"


@dataclass(frozen=True)
class ProductionReleaseArtifact:
    name: str
    digest: str

    def __post_init__(self) -> None:
        if ":latest" in self.digest or "secret" in self.digest.lower():
            raise ProductionReleaseError("production artifacts must be immutable and sanitized")


@dataclass(frozen=True)
class ProductionProviderCertification:
    provider: str
    panel_identity_digest: str
    endpoint_identity_digest: str
    credential_version_digest: str
    adapter_version: str
    contract_digest: str
    result: ProviderCertificationResult
    write_canary_result: ProviderCertificationResult
    write_enable_approved: bool
    expires_at: datetime

    def usable_for_writes(self, now: datetime) -> bool:
        return (
            self.result
            in {
                ProviderCertificationResult.PASSED,
                ProviderCertificationResult.PASSED_WITH_UNSUPPORTED_STEPS,
            }
            and self.write_canary_result == ProviderCertificationResult.PASSED
            and self.write_enable_approved
            and self.expires_at >= now
        )


@dataclass(frozen=True)
class ProductionReleasePlanVersion:
    version: int
    rc: ReleaseCandidate
    source_commit_sha: str
    application_version: str
    artifacts: tuple[ProductionReleaseArtifact, ...]
    migration_head: str
    provider_contract_digests: tuple[str, ...]
    renderer_digests: tuple[str, ...]
    environment: str
    deployment_target_reference: str
    phase_policies: tuple[PhaseType, ...]
    required_approval_roles: tuple[ApprovalRole, ...]
    evidence_expires_after: timedelta
    owner_actor_id: UUID
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.environment != "PRODUCTION" and not self.deployment_target_reference.startswith(
            "ci-fake-prod-"
        ):
            raise ProductionReleaseError(
                "production release plans require production or CI fake target"
            )
        if self.rc.finalized_at is None:
            raise ProductionReleaseError("production release plan requires finalized RC")
        if self.source_commit_sha != self.rc.source_commit_sha:
            raise ProductionReleaseError("PRODUCTION_RELEASE_RC_MISMATCH")
        if (
            self.application_version != self.rc.application_version
            or self.migration_head != self.rc.migration_head
        ):
            raise ProductionReleaseError("PRODUCTION_RELEASE_ARTIFACT_MISMATCH")
        rc_digests = set(self.rc.artifact_digests)
        if {artifact.digest for artifact in self.artifacts} != rc_digests:
            raise ProductionReleaseError("PRODUCTION_RELEASE_ARTIFACT_MISMATCH")

    def digest(self) -> str:
        payload = "|".join(
            (
                str(self.version),
                self.rc.provenance_digest(),
                self.deployment_target_reference,
                *(a.digest for a in self.artifacts),
                *self.provider_contract_digests,
                *self.renderer_digests,
                *(p.value for p in self.phase_policies),
            )
        )
        return sha256(payload.encode()).hexdigest()

    def publish(self, now: datetime) -> ProductionReleasePlanVersion:
        if self.published_at is not None:
            return self
        return replace(self, published_at=now)


@dataclass(frozen=True)
class ProductionReleaseGate:
    name: str
    state: GateState
    required: bool
    evidence_reference: str | None = None
    evidence_created_at: datetime | None = None
    expires_after: timedelta = timedelta(days=7)

    def normalized(self, now: datetime) -> ProductionReleaseGate:
        if self.state in {GateState.PASSED, GateState.PASSED_WITH_LIMITATIONS}:
            if self.evidence_reference is None or self.evidence_created_at is None:
                return replace(self, state=GateState.BLOCKED)
            if self.evidence_created_at + self.expires_after < now:
                return replace(self, state=GateState.EXPIRED)
        return self


@dataclass(frozen=True)
class ProductionReleaseApproval:
    actor_id: UUID
    role: ApprovalRole
    plan_digest: str
    approved_at: datetime


@dataclass(frozen=True)
class ProductionReleasePhasePolicy:
    phase_type: PhaseType
    basis: CohortBasis
    maximum_cohort_size: int
    exposure_basis_points: int
    minimum_observation: timedelta
    required_health_gates: tuple[str, ...]
    provider_writes_allowed: bool = False
    real_customer_canary_enabled: bool = False

    def __post_init__(self) -> None:
        if (
            self.maximum_cohort_size < 1
            or self.exposure_basis_points < 0
            or self.exposure_basis_points > 10_000
        ):
            raise ProductionReleaseError("PRODUCTION_RELEASE_PHASE_NOT_READY")
        if (
            self.phase_type == PhaseType.ALLOWLISTED_CUSTOMER
            and not self.real_customer_canary_enabled
        ):
            raise ProductionReleaseError("real customer canary is disabled by default")


@dataclass(frozen=True)
class ProductionReleaseCohortMember:
    subject_key_digest: str
    basis: CohortBasis
    eligible: bool
    exclusion_reason: str | None = None


@dataclass(frozen=True)
class ProductionReleaseCohort:
    phase_type: PhaseType
    members: tuple[ProductionReleaseCohortMember, ...]
    snapshot_at: datetime | None = None

    def snapshot(self, now: datetime) -> ProductionReleaseCohort:
        if self.snapshot_at is not None:
            return self
        return replace(self, snapshot_at=now)


def select_percentage_cohort(
    release_reference: str,
    server_key: bytes,
    candidate_keys: tuple[str, ...],
    basis_points: int,
    maximum_size: int,
) -> ProductionReleaseCohort:
    selected: list[ProductionReleaseCohortMember] = []
    for key in sorted(candidate_keys):
        digest = hmac.new(server_key, f"{release_reference}:{key}".encode(), sha256).hexdigest()
        bucket = int(digest[:8], 16) % 10_000
        if bucket < basis_points and len(selected) < maximum_size:
            selected.append(
                ProductionReleaseCohortMember(
                    subject_key_digest=digest,
                    basis=CohortBasis.DETERMINISTIC_PERCENTAGE,
                    eligible=True,
                )
            )
    return ProductionReleaseCohort(PhaseType.LOW_PERCENTAGE, tuple(selected))


@dataclass(frozen=True)
class ProductionRelease:
    release_id: UUID
    reference: str
    plan_version: ProductionReleasePlanVersion
    status: ProductionReleaseStatus
    version: int
    requester_actor_id: UUID
    approvals: tuple[ProductionReleaseApproval, ...] = ()
    history: tuple[str, ...] = ()

    @classmethod
    def create(
        cls, reference: str, plan_version: ProductionReleasePlanVersion, requester_actor_id: UUID
    ) -> ProductionRelease:
        return cls(
            uuid4(),
            reference,
            plan_version,
            ProductionReleaseStatus.DRAFT,
            1,
            requester_actor_id,
            history=("DRAFT",),
        )

    def _transition(
        self,
        allowed: set[ProductionReleaseStatus],
        new_status: ProductionReleaseStatus,
        reason: str,
    ) -> ProductionRelease:
        if self.status not in allowed:
            raise ProductionReleaseError("PRODUCTION_RELEASE_PLAN_INVALID")
        if not reason:
            raise ProductionReleaseError("reason is required")
        return replace(
            self,
            status=new_status,
            version=self.version + 1,
            history=(*self.history, f"{new_status.value}:{reason}"),
        )

    def evaluate_preflight(
        self, gates: tuple[ProductionReleaseGate, ...], now: datetime
    ) -> ProductionRelease:
        normalized = tuple(g.normalized(now) for g in gates)
        if any(
            g.required
            and g.state
            in {GateState.NOT_RUN, GateState.FAILED, GateState.BLOCKED, GateState.EXPIRED}
            for g in normalized
        ):
            return self._transition(
                {
                    ProductionReleaseStatus.DRAFT,
                    ProductionReleaseStatus.VALIDATING,
                    ProductionReleaseStatus.PREFLIGHT_FAILED,
                },
                ProductionReleaseStatus.PREFLIGHT_FAILED,
                "preflight gate blocked",
            )
        return self._transition(
            {
                ProductionReleaseStatus.DRAFT,
                ProductionReleaseStatus.VALIDATING,
                ProductionReleaseStatus.PREFLIGHT_FAILED,
            },
            ProductionReleaseStatus.READY_FOR_APPROVAL,
            "preflight passed",
        )

    def request_approval(self, actor_id: UUID) -> ProductionRelease:
        if actor_id != self.requester_actor_id:
            raise ProductionReleaseError("PRODUCTION_RELEASE_APPROVAL_REQUIRED")
        return self._transition(
            {ProductionReleaseStatus.READY_FOR_APPROVAL},
            ProductionReleaseStatus.AWAITING_APPROVAL,
            "requested",
        )

    def approve(self, actor_id: UUID, role: ApprovalRole, now: datetime) -> ProductionRelease:
        if actor_id == self.requester_actor_id:
            raise ProductionReleaseError("PRODUCTION_RELEASE_SELF_APPROVAL_DENIED")
        if role == ApprovalRole.REQUESTER:
            raise ProductionReleaseError("PRODUCTION_RELEASE_APPROVAL_REQUIRED")
        digest = self.plan_version.digest()
        approvals = tuple(a for a in self.approvals if a.role != role) + (
            ProductionReleaseApproval(actor_id, role, digest, now),
        )
        approved_roles = {a.role for a in approvals if a.plan_digest == digest}
        required = set(self.plan_version.required_approval_roles) - {ApprovalRole.REQUESTER}
        status = (
            ProductionReleaseStatus.APPROVED
            if required.issubset(approved_roles)
            and len({a.actor_id for a in approvals}) >= min(2, len(required))
            else ProductionReleaseStatus.AWAITING_APPROVAL
        )
        return replace(
            self,
            status=status,
            approvals=approvals,
            version=self.version + 1,
            history=(*self.history, f"approval:{role.value}"),
        )

    def enter_change_freeze(self, reason: str) -> ProductionRelease:
        return self._transition(
            {ProductionReleaseStatus.APPROVED}, ProductionReleaseStatus.CHANGE_FREEZE, reason
        )

    def verify_backup(self, reason: str) -> ProductionRelease:
        return self._transition(
            {ProductionReleaseStatus.CHANGE_FREEZE, ProductionReleaseStatus.BACKUP_PENDING},
            ProductionReleaseStatus.BACKUP_VERIFIED,
            reason,
        )

    def start_deployment(self, confirmation: str) -> ProductionRelease:
        expected = f"DEPLOY {self.reference} {self.plan_version.digest()[:12]}"
        if confirmation != expected:
            raise ProductionReleaseError("PRODUCTION_DEPLOYMENT_DISABLED")
        return self._transition(
            {ProductionReleaseStatus.BACKUP_VERIFIED},
            ProductionReleaseStatus.DEPLOYING,
            "operator confirmed immutable deployment",
        )

    def finish_deployment_verification(self, reason: str) -> ProductionRelease:
        return self._transition(
            {ProductionReleaseStatus.DEPLOYING, ProductionReleaseStatus.VERIFYING_DEPLOYMENT},
            ProductionReleaseStatus.CANARY_PENDING,
            reason,
        )

    def start_canary(self, reason: str) -> ProductionRelease:
        return self._transition(
            {ProductionReleaseStatus.CANARY_PENDING}, ProductionReleaseStatus.CANARY_RUNNING, reason
        )

    def pause_for_health(self, gate_name: str) -> ProductionRelease:
        return self._transition(
            {ProductionReleaseStatus.CANARY_RUNNING, ProductionReleaseStatus.PROGRESSIVE_ROLLOUT},
            ProductionReleaseStatus.CANARY_PAUSED
            if self.status == ProductionReleaseStatus.CANARY_RUNNING
            else ProductionReleaseStatus.ROLLOUT_PAUSED,
            f"health gate failed:{gate_name}",
        )

    def resume(
        self, gates: tuple[ProductionReleaseGate, ...], now: datetime, reason: str
    ) -> ProductionRelease:
        normalized = tuple(g.normalized(now) for g in gates)
        if any(
            g.required and g.state not in {GateState.PASSED, GateState.PASSED_WITH_LIMITATIONS}
            for g in normalized
        ):
            raise ProductionReleaseError("PRODUCTION_RELEASE_EVIDENCE_STALE")
        target = (
            ProductionReleaseStatus.CANARY_RUNNING
            if self.status == ProductionReleaseStatus.CANARY_PAUSED
            else ProductionReleaseStatus.PROGRESSIVE_ROLLOUT
        )
        return self._transition(
            {ProductionReleaseStatus.CANARY_PAUSED, ProductionReleaseStatus.ROLLOUT_PAUSED},
            target,
            reason,
        )

    def advance_manually(self, reason: str) -> ProductionRelease:
        return self._transition(
            {ProductionReleaseStatus.CANARY_RUNNING, ProductionReleaseStatus.PROGRESSIVE_ROLLOUT},
            ProductionReleaseStatus.PROGRESSIVE_ROLLOUT,
            reason,
        )

    def rollback(
        self, rollback_type: RollbackType, schema_compatible: bool, reason: str
    ) -> ProductionRelease:
        if rollback_type == RollbackType.APPLICATION_ARTIFACT_ROLLBACK and not schema_compatible:
            return self._transition(
                {self.status},
                ProductionReleaseStatus.MANUAL_REVIEW,
                "PRODUCTION_RELEASE_FORWARD_FIX_REQUIRED",
            )
        return self._transition({self.status}, ProductionReleaseStatus.ROLLING_BACK, reason)

    def enter_hypercare(self, reason: str) -> ProductionRelease:
        return self._transition(
            {
                ProductionReleaseStatus.PROGRESSIVE_ROLLOUT,
                ProductionReleaseStatus.FULL_EXPOSURE_PENDING,
            },
            ProductionReleaseStatus.HYPERCARE,
            reason,
        )


@dataclass(frozen=True)
class ProductionReleaseReport:
    release_reference: str
    plan_digest: str
    final_decision: FinalDecision
    phase_count: int
    cohort_count: int
    reconciliation_outcomes: tuple[ReconciliationOutcome, ...]
    sanitized_summary: str
    finalized_at: datetime

    def __post_init__(self) -> None:
        forbidden = ("secret", "token", "password", "credential", "customer:", "https://")
        if any(item in self.sanitized_summary.lower() for item in forbidden):
            raise ProductionReleaseError("secret-like release metadata")


def default_required_preflight_gates(now: datetime) -> tuple[ProductionReleaseGate, ...]:
    names = (
        "RC_FINALIZED",
        "ARTIFACT_DIGEST_MATCH",
        "CI_CHECKS",
        "CRITICAL_HIGH_DEFECTS",
        "RESTORE_DRILL",
        "PRODUCTION_CONFIGURATION",
        "SECRETS_CONFIGURED",
        "DNS_TLS",
        "ALEMBIC_ONE_HEAD",
        "SCHEMA_COMPATIBILITY",
        "ROLLBACK_ARTIFACT",
        "BACKUP_DESTINATION",
        "OBSERVABILITY_ALERTS",
        "ONCALL_SUPPORT",
        "STATUS_COMMUNICATION",
        "CAPACITY_PROVIDER_HEALTH",
        "PRODUCTION_PROVIDER_CERTIFICATION",
        "MANUAL_REVIEWS",
        "CHANGE_WINDOW",
    )
    return tuple(
        ProductionReleaseGate(name, GateState.NOT_RUN, True, expires_after=timedelta(days=7))
        for name in names
    )


def passing_gate(name: str, now: datetime) -> ProductionReleaseGate:
    return ProductionReleaseGate(name, GateState.PASSED, True, f"ci-evidence:{name}", now)
