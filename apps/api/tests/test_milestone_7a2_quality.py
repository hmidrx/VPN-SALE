from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from vpnsale_domain.quality import (
    DefectSeverity,
    DefectStatus,
    GateState,
    LoadSummary,
    PerformanceBudget,
    QualityEnvironment,
    QualityError,
    QualityProfile,
    ReleaseCandidate,
    ReleaseDecision,
    ReleaseDefect,
    ReleaseGate,
    decide_go_no_go,
    default_mixed_workload,
)


def test_quality_environment_rejects_production_targets() -> None:
    env = QualityEnvironment(QualityProfile.CI_SAFE, "https://production.example", "m7a2-ci", 4)
    with pytest.raises(QualityError, match="production"):
        env.validate()


def test_destructive_profiles_require_typed_confirmation() -> None:
    env = QualityEnvironment(
        QualityProfile.STAGING_CHAOS, "https://staging.example", "m7a2-chaos", 20
    )
    with pytest.raises(QualityError, match="confirmation"):
        env.validate()


def test_mixed_workload_requires_isolated_bounded_data() -> None:
    env = QualityEnvironment(QualityProfile.CI_SAFE, "http://localhost:8000", "m7a2-ci", 8)
    default_mixed_workload().validate(env)
    workload = default_mixed_workload("other")
    with pytest.raises(QualityError, match="isolated"):
        workload.validate(env)


def test_performance_budget_fails_duplicate_side_effects() -> None:
    budget = PerformanceBudget(800, 1500, 1, 0, 100, 60)
    summary = LoadSummary(
        "mixed", 100, 200, 0, 0, 1, 1, ledger_balanced=True, duplicate_side_effects=True
    )
    assert summary.evaluate(budget) is GateState.FAILED


def test_defect_lifecycle_blocks_until_regression_verified() -> None:
    defect = ReleaseDefect(
        "M7A2-001",
        "duplicate webhook",
        DefectSeverity.HIGH,
        DefectStatus.OPEN,
        "replay",
        "missing idempotency",
        None,
        "none",
    )
    assert defect.blocks_release
    fixed = defect.mark_fixed("test_duplicate_webhook")
    assert fixed.blocks_release
    verified = fixed.verify()
    assert not verified.blocks_release


def test_release_candidate_requires_immutable_sanitized_digests() -> None:
    with pytest.raises(QualityError, match="immutable"):
        ReleaseCandidate(
            UUID("00000000-0000-4000-8000-000000000001"),
            "ddb391a",
            "0.0.0",
            ("api:latest",),
            "head",
        )


def test_release_candidate_finalization_is_immutable() -> None:
    rc = ReleaseCandidate(
        rc_id=UUID("00000000-0000-4000-8000-000000000001"),
        source_commit_sha="ddb391a",
        application_version="0.0.0",
        artifact_digests=(
            "api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
        migration_head="0026_m7a2_quality_release",
    )
    finalized = rc.finalize(datetime(2026, 7, 18, tzinfo=UTC))
    with pytest.raises(QualityError, match="immutable"):
        finalized.finalize(datetime(2026, 7, 18, tzinfo=UTC))


def test_go_no_go_preserves_not_run_and_blocks_high_defects() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    gates = tuple(
        ReleaseGate(name, GateState.PASSED, f"evidence/{name}", now)
        for name in (
            "REQUIRED_CI",
            "AUTHORIZATION_MATRIX",
            "LOAD_BASELINE",
            "BACKUP_RESTORE",
            "CHAOS_RECOVERY",
            "CRITICAL_HIGH_DEFECTS",
        )
    )
    defect = ReleaseDefect(
        "M7A2-002",
        "tenant leak",
        DefectSeverity.CRITICAL,
        DefectStatus.OPEN,
        "cross-read",
        "missing owner filter",
        None,
        "blocks release",
    )
    assert decide_go_no_go(gates, (defect,), now) is ReleaseDecision.NO_GO
    assert (
        decide_go_no_go(gates, (defect.mark_fixed("test_owner_filter").verify(),), now)
        is ReleaseDecision.READY_FOR_RC_REVIEW
    )


def test_completed_gate_requires_evidence_and_stale_evidence_expires() -> None:
    now = datetime(2026, 7, 18, tzinfo=UTC)
    with pytest.raises(QualityError, match="evidence"):
        ReleaseGate("LOAD_BASELINE", GateState.PASSED, None, None).normalized(now)
    stale = ReleaseGate(
        "LOAD_BASELINE", GateState.PASSED, "evidence/load", now - timedelta(days=30)
    )
    assert stale.normalized(now).state is GateState.EXPIRED
