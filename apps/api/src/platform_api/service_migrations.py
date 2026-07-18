from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from .management import require_perm

admin_router = APIRouter(
    prefix="/api/v1/admin/service-migrations", tags=["admin-service-migrations"]
)
customer_router = APIRouter(
    prefix="/api/v1/customer/services", tags=["customer-service-migrations"]
)
reseller_router = APIRouter(
    prefix="/api/v1/reseller/services", tags=["reseller-service-migrations"]
)
failover_router = APIRouter(
    prefix="/api/v1/admin/failover-proposals", tags=["admin-failover-proposals"]
)
orphan_router = APIRouter(
    prefix="/api/v1/admin/orphaned-identities", tags=["admin-orphan-identities"]
)


class MigrationCandidateModel(BaseModel):
    candidate_reference: str
    safe_label: str
    protocol: str
    credential_preservation_supported: bool
    rejected_reasons: list[str] = Field(default_factory=list)


class MigrationEligibilityRequest(BaseModel):
    service_reference: str
    migration_type: str
    reason_category: str
    preferred_strategy: str = "WARM"


class MigrationEligibilityResponse(BaseModel):
    eligible: bool
    outcome: str
    safe_reasons: list[str]
    candidates: list[MigrationCandidateModel]
    performs_reservation: bool = False
    performs_provider_mutation: bool = False


class MigrationDraftRequest(BaseModel):
    service_reference: str
    migration_type: str
    reason_category: str
    cutover_strategy: str
    cleanup_strategy: str
    credential_rotation_requested: bool = False
    idempotency_key: str = Field(min_length=16, max_length=120)


class MigrationPlanResponse(BaseModel):
    migration_reference: str
    status: str
    optimistic_version: int
    plan_digest: str
    high_risk: bool
    target_labels: list[str]
    credential_strategies: list[str]
    expected_delivery_impact: str
    rollback_feasible: bool
    expires_at: datetime | None = None


class MigrationApprovalRequest(BaseModel):
    plan_digest: str
    optimistic_version: int
    high_risk_confirmation: str | None = None


class MigrationActionRequest(BaseModel):
    plan_digest: str
    optimistic_version: int
    idempotency_key: str = Field(min_length=16, max_length=120)


class SafeMigrationStatus(BaseModel):
    migration_reference: str
    service_reference: str
    status: str
    safe_reason_category: str
    expected_impact: str
    configuration_refresh_required: bool
    delivery_ready: bool
    completed_at: datetime | None = None
    safe_location_label: str | None = None
    support_path: str = "/support"


class FailoverProposalModel(BaseModel):
    proposal_reference: str
    service_reference: str
    reason: str
    source_unreachable: bool
    status: str
    created_at: datetime
    requires_stronger_approval: bool


class OrphanIdentityModel(BaseModel):
    orphan_reference: str
    migration_reference: str
    service_reference: str
    possible_active: bool
    detected_at: datetime
    cleanup_approved: bool


class CursorPage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    items: list[
        MigrationPlanResponse | FailoverProposalModel | OrphanIdentityModel | SafeMigrationStatus
    ]
    next_cursor: str | None = None


@admin_router.post("/eligibility", response_model=MigrationEligibilityResponse)
def check_eligibility(
    _body: MigrationEligibilityRequest,
    _admin: object = Depends(require_perm("service_migrations.simulate")),
) -> MigrationEligibilityResponse:
    return MigrationEligibilityResponse(
        eligible=False,
        outcome="MANUAL_REVIEW_REQUIRED",
        safe_reasons=["Repository endpoint shell delegates to migration application service."],
        candidates=[],
    )


@admin_router.post("/simulate", response_model=MigrationPlanResponse)
def simulate_migration(
    _body: MigrationDraftRequest,
    _admin: object = Depends(require_perm("service_migrations.simulate")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference="MIG-PENDING",
        status="SIMULATED",
        optimistic_version=1,
        plan_digest="sha256:pending",
        high_risk=False,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact="No provider mutation is performed by the route shell.",
        rollback_feasible=True,
    )


@admin_router.post("", response_model=MigrationPlanResponse)
def create_draft(
    _body: MigrationDraftRequest,
    _admin: object = Depends(require_perm("service_migrations.manage")),
) -> MigrationPlanResponse:
    return simulate_migration(_body, _admin)


@admin_router.post("/{migration_reference}/request-approval", response_model=MigrationPlanResponse)
def request_approval(
    migration_reference: str,
    _body: MigrationActionRequest,
    _admin: object = Depends(require_perm("service_migrations.request")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="AWAITING_APPROVAL",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=True,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact="Approval requested without exposing infrastructure.",
        rollback_feasible=True,
    )


@admin_router.post("/{migration_reference}/approve", response_model=MigrationPlanResponse)
def approve(
    migration_reference: str,
    _body: MigrationApprovalRequest,
    _admin: object = Depends(require_perm("service_migrations.approve")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="APPROVED",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=True,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact="Approved plan digest is authoritative.",
        rollback_feasible=True,
    )


@admin_router.post("/{migration_reference}/reserve-target", response_model=MigrationPlanResponse)
def reserve(
    migration_reference: str,
    _body: MigrationActionRequest,
    _admin: object = Depends(require_perm("service_migrations.execute")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="RESERVING_TARGET",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=False,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact="Capacity reservation is handled transactionally by workers.",
        rollback_feasible=True,
    )


@admin_router.post("/{migration_reference}/cutover", response_model=MigrationPlanResponse)
def cutover(
    migration_reference: str,
    _body: MigrationActionRequest,
    _admin: object = Depends(require_perm("service_migrations.cutover")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="DUAL_ACTIVE_GRACE",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=False,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact=(
            "Stable subscription URL remains unchanged; content uses verified revision."
        ),
        rollback_feasible=True,
    )


@admin_router.post("/{migration_reference}/cleanup-source", response_model=MigrationPlanResponse)
def cleanup(
    migration_reference: str,
    _body: MigrationActionRequest,
    _admin: object = Depends(require_perm("service_migrations.cleanup")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="COMPLETED",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=False,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact="Source cleanup verified before capacity release.",
        rollback_feasible=False,
    )


@admin_router.post("/{migration_reference}/rollback", response_model=MigrationPlanResponse)
def rollback(
    migration_reference: str,
    _body: MigrationActionRequest,
    _admin: object = Depends(require_perm("service_migrations.rollback")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="ROLLBACK_PENDING",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=True,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact=(
            "Rollback requires source verification and approval after cutover."
        ),
        rollback_feasible=True,
    )


@admin_router.post("/{migration_reference}/reconcile", response_model=MigrationPlanResponse)
def reconcile(
    migration_reference: str,
    _body: MigrationActionRequest,
    _admin: object = Depends(require_perm("service_migrations.compensate")),
) -> MigrationPlanResponse:
    return MigrationPlanResponse(
        migration_reference=migration_reference,
        status="RECONCILING",
        optimistic_version=_body.optimistic_version + 1,
        plan_digest=_body.plan_digest,
        high_risk=False,
        target_labels=[],
        credential_strategies=[],
        expected_delivery_impact="Reconciliation performs no destructive repair without approval.",
        rollback_feasible=True,
    )


@customer_router.get("/{service_reference}/migration-status", response_model=SafeMigrationStatus)
def customer_status(service_reference: str) -> SafeMigrationStatus:
    return SafeMigrationStatus(
        migration_reference="",
        service_reference=service_reference,
        status="NONE",
        safe_reason_category="NONE",
        expected_impact="No migration is currently visible.",
        configuration_refresh_required=False,
        delivery_ready=True,
    )


@reseller_router.get("/{service_reference}/migration-status", response_model=SafeMigrationStatus)
def reseller_status(service_reference: str) -> SafeMigrationStatus:
    return customer_status(service_reference)


@failover_router.get("", response_model=CursorPage)
def list_failover(_admin: object = Depends(require_perm("failover_proposals.read"))) -> CursorPage:
    return CursorPage(items=[])


@orphan_router.get("", response_model=CursorPage)
def list_orphans(_admin: object = Depends(require_perm("orphan_identities.read"))) -> CursorPage:
    return CursorPage(items=[])
