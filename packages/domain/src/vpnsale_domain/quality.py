from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from uuid import UUID, uuid4


class QualityProfile(StrEnum):
    CI_SAFE = "CI_SAFE"
    LOCAL_ISOLATED = "LOCAL_ISOLATED"
    STAGING_STANDARD = "STAGING_STANDARD"
    STAGING_LOAD = "STAGING_LOAD"
    STAGING_SECURITY = "STAGING_SECURITY"
    STAGING_CHAOS = "STAGING_CHAOS"


class GateState(StrEnum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    PASSED_WITH_LIMITATIONS = "PASSED_WITH_LIMITATIONS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class ReleaseDecision(StrEnum):
    NO_GO = "NO_GO"
    READY_FOR_RC_REVIEW = "READY_FOR_RC_REVIEW"
    READY_FOR_CONTROLLED_CANARY_REVIEW = "READY_FOR_CONTROLLED_CANARY_REVIEW"


class DefectSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DefectStatus(StrEnum):
    OPEN = "OPEN"
    FIXED_PENDING_VERIFICATION = "FIXED_PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DEFERRED = "DEFERRED"


class QualityError(ValueError):
    pass


@dataclass(frozen=True)
class QualityEnvironment:
    profile: QualityProfile
    base_origin: str
    tenant_prefix: str
    max_virtual_users: int
    destructive_confirmation: str | None = None
    allow_provider_writes: bool = False

    def validate(self) -> None:
        origin = self.base_origin.lower()
        forbidden = ("prod", "production", "vpn-sale.ir", "www.")
        if any(marker in origin for marker in forbidden):
            raise QualityError("production targets are rejected")
        if not self.base_origin.startswith(
            ("http://127.0.0.1", "http://localhost", "https://staging.")
        ):
            raise QualityError("target origin is not allowlisted")
        if not self.tenant_prefix.startswith("m7a2-") or len(self.tenant_prefix) > 40:
            raise QualityError("synthetic tenant prefix is invalid")
        if self.max_virtual_users < 1 or self.max_virtual_users > 500:
            raise QualityError("virtual user bound is invalid")
        if self.profile in {QualityProfile.STAGING_LOAD, QualityProfile.STAGING_CHAOS}:
            expected = f"CONFIRM-{self.profile.value}-{self.tenant_prefix}"
            if self.destructive_confirmation != expected:
                raise QualityError("typed confirmation is required")
        if self.allow_provider_writes and self.profile not in {
            QualityProfile.STAGING_STANDARD,
            QualityProfile.STAGING_LOAD,
        }:
            raise QualityError("provider writes require certified staging profile")


@dataclass(frozen=True)
class WorkloadProfile:
    name: str
    journeys: tuple[str, ...]
    virtual_users: int
    warmup_seconds: int
    duration_seconds: int
    cooldown_seconds: int
    tenant_prefix: str

    def validate(self, environment: QualityEnvironment) -> None:
        environment.validate()
        if self.virtual_users > environment.max_virtual_users:
            raise QualityError("workload exceeds environment concurrency bound")
        if len(set(self.journeys)) < 3:
            raise QualityError("workload must cover multiple critical journeys")
        if not self.tenant_prefix.startswith(environment.tenant_prefix):
            raise QualityError("workload data is not isolated to the test tenant")
        if self.duration_seconds > 21_600 or self.warmup_seconds < 0 or self.cooldown_seconds < 0:
            raise QualityError("workload duration is outside bounded limits")


@dataclass(frozen=True)
class PerformanceBudget:
    p95_latency_ms: int
    p99_latency_ms: int
    error_rate_percent: int
    timeout_rate_percent: int
    max_queue_depth: int
    max_outbox_lag_seconds: int


@dataclass(frozen=True)
class LoadSummary:
    workload_name: str
    p95_latency_ms: int
    p99_latency_ms: int
    error_rate_percent: int
    timeout_rate_percent: int
    max_queue_depth: int
    max_outbox_lag_seconds: int
    ledger_balanced: bool
    duplicate_side_effects: bool

    def evaluate(self, budget: PerformanceBudget) -> GateState:
        if not self.ledger_balanced or self.duplicate_side_effects:
            return GateState.FAILED
        if (
            self.p95_latency_ms <= budget.p95_latency_ms
            and self.p99_latency_ms <= budget.p99_latency_ms
            and self.error_rate_percent <= budget.error_rate_percent
            and self.timeout_rate_percent <= budget.timeout_rate_percent
            and self.max_queue_depth <= budget.max_queue_depth
            and self.max_outbox_lag_seconds <= budget.max_outbox_lag_seconds
        ):
            return GateState.PASSED
        return GateState.FAILED


@dataclass(frozen=True)
class ReleaseDefect:
    reference: str
    title: str
    severity: DefectSeverity
    status: DefectStatus
    reproduction: str
    root_cause: str
    regression_test: str | None
    residual_risk: str

    @property
    def blocks_release(self) -> bool:
        return (
            self.severity in {DefectSeverity.CRITICAL, DefectSeverity.HIGH}
            and self.status != DefectStatus.VERIFIED
        )

    def mark_fixed(self, regression_test: str) -> ReleaseDefect:
        if not regression_test:
            raise QualityError("fixed defects require regression-test reference")
        return replace(
            self, status=DefectStatus.FIXED_PENDING_VERIFICATION, regression_test=regression_test
        )

    def verify(self) -> ReleaseDefect:
        if self.status != DefectStatus.FIXED_PENDING_VERIFICATION or not self.regression_test:
            raise QualityError("verification requires fixed status and regression evidence")
        return replace(self, status=DefectStatus.VERIFIED)


@dataclass(frozen=True)
class ReleaseGate:
    name: str
    state: GateState
    evidence_reference: str | None
    evidence_created_at: datetime | None
    expires_after: timedelta = timedelta(days=14)

    def normalized(self, now: datetime) -> ReleaseGate:
        if self.state in {GateState.PASSED, GateState.PASSED_WITH_LIMITATIONS}:
            if not self.evidence_reference or self.evidence_created_at is None:
                raise QualityError("completed gates require evidence")
            if self.evidence_created_at + self.expires_after < now:
                return replace(self, state=GateState.EXPIRED)
        return self


@dataclass(frozen=True)
class ReleaseCandidate:
    rc_id: UUID
    source_commit_sha: str
    application_version: str
    artifact_digests: tuple[str, ...]
    migration_head: str
    finalized_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.source_commit_sha) < 7 or not self.artifact_digests:
            raise QualityError("release candidate provenance is incomplete")
        if any(
            digest.endswith(":latest") or "secret" in digest.lower()
            for digest in self.artifact_digests
        ):
            raise QualityError("release candidate artifacts must be immutable and sanitized")

    def provenance_digest(self) -> str:
        payload = "|".join(
            (
                self.source_commit_sha,
                self.application_version,
                self.migration_head,
                *self.artifact_digests,
            )
        )
        return sha256(payload.encode()).hexdigest()

    def finalize(self, now: datetime) -> ReleaseCandidate:
        if self.finalized_at is not None:
            raise QualityError("finalized release candidates are immutable")
        return replace(self, finalized_at=now)


def decide_go_no_go(
    gates: tuple[ReleaseGate, ...], defects: tuple[ReleaseDefect, ...], now: datetime
) -> ReleaseDecision:
    normalized = tuple(gate.normalized(now) for gate in gates)
    if any(defect.blocks_release for defect in defects):
        return ReleaseDecision.NO_GO
    required = {
        "REQUIRED_CI",
        "AUTHORIZATION_MATRIX",
        "LOAD_BASELINE",
        "BACKUP_RESTORE",
        "CHAOS_RECOVERY",
        "CRITICAL_HIGH_DEFECTS",
    }
    required_gates = {gate.name: gate.state for gate in normalized if gate.name in required}
    if required_gates.keys() != required:
        return ReleaseDecision.NO_GO
    if all(
        state in {GateState.PASSED, GateState.PASSED_WITH_LIMITATIONS}
        for state in required_gates.values()
    ):
        if all(gate.state != GateState.FAILED for gate in normalized):
            return ReleaseDecision.READY_FOR_RC_REVIEW
    return ReleaseDecision.NO_GO


def default_mixed_workload(tenant_prefix: str = "m7a2-ci") -> WorkloadProfile:
    return WorkloadProfile(
        name="mixed-critical-journeys-ci-safe",
        journeys=(
            "catalog",
            "auth",
            "checkout",
            "payment-webhook",
            "fulfillment",
            "subscription",
            "support",
            "fleet",
        ),
        virtual_users=8,
        warmup_seconds=15,
        duration_seconds=120,
        cooldown_seconds=15,
        tenant_prefix=tenant_prefix,
    )


def synthetic_rc(commit: str) -> ReleaseCandidate:
    return ReleaseCandidate(
        rc_id=uuid4(),
        source_commit_sha=commit,
        application_version="0.0.0-m7a2",
        artifact_digests=(
            "api@sha256:0000000000000000000000000000000000000000000000000000000000000000",
        ),
        migration_head="0026_m7a2_quality_release",
        finalized_at=datetime.now(UTC),
    )
