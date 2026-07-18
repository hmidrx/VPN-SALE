from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from vpnsale_domain.production_releases import (
    ApprovalRole,
    CohortBasis,
    FinalDecision,
    PhaseType,
    ProductionProviderCertification,
    ProductionRelease,
    ProductionReleaseArtifact,
    ProductionReleaseError,
    ProductionReleaseGate,
    ProductionReleasePhasePolicy,
    ProductionReleasePlanVersion,
    ProductionReleaseReport,
    ProductionReleaseStatus,
    ProviderCertificationResult,
    ReconciliationOutcome,
    RollbackType,
    default_required_preflight_gates,
    passing_gate,
    select_percentage_cohort,
)
from vpnsale_domain.quality import GateState, ReleaseCandidate

NOW = datetime(2026, 7, 18, tzinfo=UTC)


def finalized_rc() -> ReleaseCandidate:
    return ReleaseCandidate(
        rc_id=uuid4(),
        source_commit_sha="abc1234567890",
        application_version="7.0.0",
        artifact_digests=("api@sha256:" + "a" * 64, "web@sha256:" + "b" * 64),
        migration_head="0027_m7b_prod_rollout",
    ).finalize(NOW)


def plan(owner: object | None = None) -> ProductionReleasePlanVersion:
    rc = finalized_rc()
    return ProductionReleasePlanVersion(
        version=1,
        rc=rc,
        source_commit_sha=rc.source_commit_sha,
        application_version=rc.application_version,
        artifacts=tuple(
            ProductionReleaseArtifact(f"artifact-{i}", digest)
            for i, digest in enumerate(rc.artifact_digests)
        ),
        migration_head=rc.migration_head,
        provider_contract_digests=("contract:3x-ui:v3.5.0",),
        renderer_digests=("renderer:v1:sha256",),
        environment="CI",
        deployment_target_reference="ci-fake-prod-rollout",
        phase_policies=(
            PhaseType.DEPLOYMENT_SMOKE,
            PhaseType.SYNTHETIC_INTERNAL,
            PhaseType.LOW_PERCENTAGE,
        ),
        required_approval_roles=(
            ApprovalRole.RELEASE_APPROVER,
            ApprovalRole.DEPLOYMENT_APPROVER,
            ApprovalRole.SECURITY_APPROVER,
        ),
        evidence_expires_after=timedelta(days=7),
        owner_actor_id=owner if isinstance(owner, UUID) else uuid4(),
    ).publish(NOW)


def release() -> ProductionRelease:
    requester = uuid4()
    return ProductionRelease.create("prod-rel-7b-ci", plan(requester), requester)


def test_plan_binds_one_finalized_rc_and_rejects_mismatch() -> None:
    rc = finalized_rc()
    with pytest.raises(ProductionReleaseError, match="PRODUCTION_RELEASE_ARTIFACT_MISMATCH"):
        ProductionReleasePlanVersion(
            version=1,
            rc=rc,
            source_commit_sha=rc.source_commit_sha,
            application_version=rc.application_version,
            artifacts=(ProductionReleaseArtifact("api", rc.artifact_digests[0]),),
            migration_head=rc.migration_head,
            provider_contract_digests=(),
            renderer_digests=(),
            environment="CI",
            deployment_target_reference="ci-fake-prod-rollout",
            phase_policies=(PhaseType.DEPLOYMENT_SMOKE,),
            required_approval_roles=(ApprovalRole.RELEASE_APPROVER,),
            evidence_expires_after=timedelta(days=7),
            owner_actor_id=uuid4(),
        )


def test_preflight_keeps_not_run_and_stale_evidence_blocking() -> None:
    rel = release()
    assert (
        rel.evaluate_preflight(default_required_preflight_gates(NOW), NOW).status
        == ProductionReleaseStatus.PREFLIGHT_FAILED
    )
    stale = (
        ProductionReleaseGate(
            "RC_FINALIZED",
            GateState.PASSED,
            True,
            "old",
            NOW - timedelta(days=10),
            timedelta(days=1),
        ),
    )
    assert rel.evaluate_preflight(stale, NOW).status == ProductionReleaseStatus.PREFLIGHT_FAILED


def test_approval_separation_and_self_approval_denial() -> None:
    rel = release().evaluate_preflight(
        tuple(passing_gate(g.name, NOW) for g in default_required_preflight_gates(NOW)), NOW
    )
    rel = rel.request_approval(rel.requester_actor_id)
    with pytest.raises(ProductionReleaseError, match="SELF_APPROVAL"):
        rel.approve(rel.requester_actor_id, ApprovalRole.RELEASE_APPROVER, NOW)
    actor_a = uuid4()
    actor_b = uuid4()
    actor_c = uuid4()
    rel = rel.approve(actor_a, ApprovalRole.RELEASE_APPROVER, NOW)
    assert rel.status == ProductionReleaseStatus.AWAITING_APPROVAL
    rel = rel.approve(actor_b, ApprovalRole.DEPLOYMENT_APPROVER, NOW)
    rel = rel.approve(actor_c, ApprovalRole.SECURITY_APPROVER, NOW)
    assert rel.status == ProductionReleaseStatus.APPROVED


def test_change_freeze_backup_deployment_canary_manual_progression() -> None:
    rel = release().evaluate_preflight(
        tuple(passing_gate(g.name, NOW) for g in default_required_preflight_gates(NOW)), NOW
    )
    rel = rel.request_approval(rel.requester_actor_id)
    for role in (
        ApprovalRole.RELEASE_APPROVER,
        ApprovalRole.DEPLOYMENT_APPROVER,
        ApprovalRole.SECURITY_APPROVER,
    ):
        rel = rel.approve(uuid4(), role, NOW)
    rel = rel.enter_change_freeze("freeze approved")
    rel = rel.verify_backup("encrypted backup verified")
    with pytest.raises(ProductionReleaseError, match="DEPLOYMENT_DISABLED"):
        rel.start_deployment("DEPLOY wrong")
    rel = rel.start_deployment(f"DEPLOY {rel.reference} {rel.plan_version.digest()[:12]}")
    rel = rel.finish_deployment_verification("smoke passed")
    rel = rel.start_canary("operator starts canary")
    assert rel.status == ProductionReleaseStatus.CANARY_RUNNING
    assert ProductionReleaseStatus.PROGRESSIVE_ROLLOUT not in [
        ProductionReleaseStatus.CANARY_RUNNING
    ]
    rel = rel.advance_manually("operator advances after observation")
    assert rel.status == ProductionReleaseStatus.PROGRESSIVE_ROLLOUT


def test_deterministic_cohort_selection_and_snapshot_immutability() -> None:
    cohort_a = select_percentage_cohort(
        "rel", b"server-held-key", tuple(f"acct-{i}" for i in range(100)), 1500, 10
    )
    cohort_b = select_percentage_cohort(
        "rel", b"server-held-key", tuple(reversed([f"acct-{i}" for i in range(100)])), 1500, 10
    )
    assert cohort_a.members == cohort_b.members
    assert len(cohort_a.members) <= 10
    snap = cohort_a.snapshot(NOW)
    assert snap.snapshot(NOW + timedelta(hours=1)).snapshot_at == NOW
    assert all("acct-" not in m.subject_key_digest for m in snap.members)


def test_real_customer_canary_disabled_by_default() -> None:
    with pytest.raises(ProductionReleaseError, match="disabled by default"):
        ProductionReleasePhasePolicy(
            PhaseType.ALLOWLISTED_CUSTOMER,
            CohortBasis.ALLOWLISTED_CUSTOMER,
            1,
            0,
            timedelta(minutes=30),
            ("api",),
        )


def test_provider_production_certification_write_gate() -> None:
    cert = ProductionProviderCertification(
        "3x-ui",
        "panel-digest",
        "endpoint-digest",
        "credential-version-digest",
        "adapter-v1",
        "contract-digest",
        ProviderCertificationResult.NOT_RUN,
        ProviderCertificationResult.NOT_RUN,
        False,
        NOW + timedelta(days=1),
    )
    assert not cert.usable_for_writes(NOW)
    passed = ProductionProviderCertification(
        "3x-ui",
        "panel-digest",
        "endpoint-digest",
        "credential-version-digest",
        "adapter-v1",
        "contract-digest",
        ProviderCertificationResult.PASSED,
        ProviderCertificationResult.PASSED,
        True,
        NOW + timedelta(days=1),
    )
    assert passed.usable_for_writes(NOW)


def test_health_pause_resume_and_schema_incompatible_rollback() -> None:
    rel = release().evaluate_preflight(
        tuple(passing_gate(g.name, NOW) for g in default_required_preflight_gates(NOW)), NOW
    )
    rel = rel.request_approval(rel.requester_actor_id)
    for role in (
        ApprovalRole.RELEASE_APPROVER,
        ApprovalRole.DEPLOYMENT_APPROVER,
        ApprovalRole.SECURITY_APPROVER,
    ):
        rel = rel.approve(uuid4(), role, NOW)
    rel = (
        rel.enter_change_freeze("freeze")
        .verify_backup("backup")
        .start_deployment(f"DEPLOY {rel.reference} {rel.plan_version.digest()[:12]}")
        .finish_deployment_verification("ok")
        .start_canary("start")
    )
    paused = rel.pause_for_health("ledger_invariant")
    assert paused.status == ProductionReleaseStatus.CANARY_PAUSED
    with pytest.raises(ProductionReleaseError, match="EVIDENCE_STALE"):
        paused.resume((ProductionReleaseGate("api", GateState.EXPIRED, True),), NOW, "fixed")
    resumed = paused.resume((passing_gate("api", NOW),), NOW, "root cause fixed")
    assert resumed.status == ProductionReleaseStatus.CANARY_RUNNING
    assert (
        resumed.rollback(RollbackType.APPLICATION_ARTIFACT_ROLLBACK, False, "regression").status
        == ProductionReleaseStatus.MANUAL_REVIEW
    )


def test_final_report_is_immutable_and_sanitized() -> None:
    report = ProductionReleaseReport(
        "rel",
        "digest",
        FinalDecision.CONTROLLED_ROLLOUT_COMPLETED,
        3,
        10,
        (ReconciliationOutcome.MATCHED,),
        "bounded synthetic evidence only",
        NOW,
    )
    assert report.final_decision == FinalDecision.CONTROLLED_ROLLOUT_COMPLETED
    with pytest.raises(ProductionReleaseError, match="secret-like"):
        ProductionReleaseReport(
            "rel",
            "digest",
            FinalDecision.COMPLETED_WITH_LIMITATIONS,
            1,
            1,
            (ReconciliationOutcome.MANUAL_REVIEW_REQUIRED,),
            "contains token value",
            NOW,
        )
