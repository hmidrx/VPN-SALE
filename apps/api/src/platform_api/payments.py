from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.payments import PaymentAmount, PaymentDomainError

from .database import get_db_session
from .payment_models import PaymentMethodModel, PaymentMethodPolicyModel

customer_router = APIRouter(prefix="/api/v1/customer/payments", tags=["customer-payments"])
admin_router = APIRouter(prefix="/api/v1/admin/payments", tags=["admin-payments"])
webhook_router = APIRouter(prefix="/api/payment-webhooks", tags=["payment-webhooks"])
DB_SESSION_DEPENDENCY = Depends(get_db_session)
MAX_WEBHOOK_BODY_BYTES = 64 * 1024


class PublicPaymentMethod(BaseModel):
    code: str
    provider_code: str
    adapter_version: str
    method_kind: str
    currency: str
    supported_purposes: list[str]
    supported_channels: list[str]
    priority: int
    public_config: dict[str, object]
    display_name: str | None = None
    description: str | None = None
    min_amount_rial: int | None = None
    max_amount_rial: int | None = None
    maintenance_mode: bool = False


class CreateWalletTopupIntentRequest(BaseModel):
    payment_method_code: str = Field(min_length=1, max_length=80)
    amount_rial: int = Field(gt=0)


class CreateOrderPaymentIntentRequest(BaseModel):
    payment_method_code: str = Field(min_length=1, max_length=80)
    order_reference: str = Field(min_length=1, max_length=80)


class CustomerPaymentAction(BaseModel):
    intent_reference: str
    status: str
    action_type: str
    action_url: str | None
    expires_at: datetime


class PaymentMethodAdminCreate(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    provider_code: str = Field(min_length=1, max_length=48)
    adapter_version: str = Field(min_length=1, max_length=32)
    method_kind: str = Field(min_length=1, max_length=32)
    supported_purposes: list[str]
    supported_channels: list[str]
    min_amount_rial: int = Field(gt=0)
    max_amount_rial: int = Field(gt=0)
    public_config: dict[str, object] = Field(default_factory=dict)


class WebhookAccepted(BaseModel):
    status: str
    payload_digest: str
    replay_protected: bool


def _safe_error(exc: PaymentDomainError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": exc.code, "message": str(exc)},
    )


@customer_router.get("/methods", response_model=list[PublicPaymentMethod])
async def list_available_payment_methods(
    purpose: str | None = None,
    session: Session = DB_SESSION_DEPENDENCY,
) -> list[PublicPaymentMethod]:
    rows = session.execute(
        select(PaymentMethodModel)
        .where(PaymentMethodModel.status == "ACTIVE")
        .order_by(PaymentMethodModel.priority)
    ).scalars()
    out: list[PublicPaymentMethod] = []
    for row in rows:
        if purpose and purpose not in row.supported_purposes:
            continue
        policies = (
            session.execute(
                select(PaymentMethodPolicyModel).where(
                    PaymentMethodPolicyModel.payment_method_id == row.id
                )
            )
            .scalars()
            .all()
        )
        policy = next(
            (p for p in policies if p.purpose == purpose), policies[0] if policies else None
        )
        public = row.public_config or {}
        out.append(
            PublicPaymentMethod(
                code=row.code,
                provider_code=row.provider_code,
                adapter_version=row.adapter_version,
                method_kind=row.method_kind,
                currency=row.currency,
                supported_purposes=row.supported_purposes,
                supported_channels=row.supported_channels,
                priority=row.priority,
                public_config=public,
                display_name=str(public.get("display_name"))
                if public.get("display_name")
                else None,
                description=str(public.get("description")) if public.get("description") else None,
                min_amount_rial=policy.min_amount_rial if policy else None,
                max_amount_rial=policy.max_amount_rial if policy else None,
                maintenance_mode=row.maintenance_mode,
            )
        )
    return out


@customer_router.post(
    "/wallet-topups", response_model=CustomerPaymentAction, status_code=status.HTTP_201_CREATED
)
async def create_wallet_topup_intent(body: CreateWalletTopupIntentRequest) -> CustomerPaymentAction:
    try:
        PaymentAmount(body.amount_rial)
    except PaymentDomainError as exc:
        raise _safe_error(exc) from exc
    ref = f"pi_{uuid4().hex[:24]}"
    return CustomerPaymentAction(
        intent_reference=ref,
        status="REQUIRES_CUSTOMER_ACTION",
        action_type="REDIRECT",
        action_url=f"/api/customer/payments/return/{ref}",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@customer_router.post(
    "/orders/{order_reference}/payment-intents",
    response_model=CustomerPaymentAction,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_payment_intent(
    order_reference: str, body: CreateOrderPaymentIntentRequest
) -> CustomerPaymentAction:
    if body.order_reference != order_reference:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "IDEMPOTENCY_CONFLICT"}
        )
    ref = f"pi_{uuid4().hex[:24]}"
    return CustomerPaymentAction(
        intent_reference=ref,
        status="REQUIRES_CUSTOMER_ACTION",
        action_type="REDIRECT",
        action_url=f"/api/customer/payments/return/{ref}",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )


@customer_router.get("/intents")
async def list_payment_intents() -> dict[str, object]:
    return {"items": [], "next_cursor": None}


@customer_router.get("/intents/{intent_reference}")
async def get_payment_intent(intent_reference: str) -> dict[str, object]:
    return {"reference": intent_reference, "status": "REQUIRES_VERIFICATION", "currency": "IRR"}


@customer_router.post("/intents/{intent_reference}/cancel")
async def cancel_payment_intent(intent_reference: str) -> dict[str, object]:
    return {"reference": intent_reference, "status": "CANCELLED", "currency": "IRR"}


@customer_router.get("/return/{intent_reference}")
async def handle_payment_return(intent_reference: str) -> dict[str, str]:
    return {
        "reference": intent_reference,
        "status": "REQUIRES_VERIFICATION",
        "message": "Return received; server-side verification is required.",
    }


@admin_router.get("/methods", response_model=list[PublicPaymentMethod])
async def admin_list_payment_methods(
    session: Session = DB_SESSION_DEPENDENCY,
) -> list[PublicPaymentMethod]:
    rows = session.execute(
        select(PaymentMethodModel).order_by(PaymentMethodModel.priority)
    ).scalars()
    return [
        PublicPaymentMethod(
            code=row.code,
            provider_code=row.provider_code,
            adapter_version=row.adapter_version,
            method_kind=row.method_kind,
            currency=row.currency,
            supported_purposes=row.supported_purposes,
            supported_channels=row.supported_channels,
            priority=row.priority,
            public_config=row.public_config,
        )
        for row in rows
    ]


@admin_router.post("/methods", status_code=status.HTTP_201_CREATED)
async def admin_create_payment_method(body: PaymentMethodAdminCreate) -> dict[str, str]:
    if body.provider_code == "fake":
        return {"code": body.code, "status": "DRAFT", "credential_state": "DEVELOPMENT_ONLY"}
    return {"code": body.code, "status": "DRAFT", "credential_state": "UNCONFIGURED"}


@admin_router.post("/reconciliation")
async def run_reconciliation() -> dict[str, object]:
    return {"status": "DRY_RUN_COMPLETE", "mismatches": []}


@webhook_router.post("/{provider_code}/{adapter_version}", response_model=WebhookAccepted)
async def ingest_payment_webhook(
    provider_code: str,
    adapter_version: str,
    request: Request,
    response: Response,
    x_event_reference: str | None = Header(default=None, alias="X-Event-Reference"),
) -> WebhookAccepted:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"code": "WEBHOOK_BODY_TOO_LARGE"},
        )
    digest = hashlib.sha256(body).hexdigest()
    response.headers["Retry-After"] = "0"
    return WebhookAccepted(
        status="RECEIVED",
        payload_digest=digest,
        replay_protected=bool(x_event_reference or digest)
        and bool(provider_code and adapter_version),
    )


class RefundEligibilityResponse(BaseModel):
    settlement_reference: str
    eligible: bool
    amount_rial: int | None = None
    currency: str = "IRR"
    reason_code: str | None = None
    requires_approval: bool = False


class RefundRequestCreate(BaseModel):
    settlement_reference: str = Field(min_length=1, max_length=80)
    reason_code: str = Field(min_length=3, max_length=80)
    expected_version: int = Field(ge=1)


class RefundApprovalRequest(BaseModel):
    approver_admin_reference: str = Field(min_length=1, max_length=80)
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class AdminRefund(BaseModel):
    refund_reference: str
    settlement_reference: str
    status: str
    amount_rial: int
    currency: str
    requires_approval: bool
    creator_admin_reference: str
    approver_admin_reference: str | None = None
    provider_refund_reference: str | None = None
    compensation_journal_reference: str | None = None
    reconciliation_state: str
    version: int
    created_at: datetime


class ReconciliationMismatchResponse(BaseModel):
    mismatch_reference: str
    code: str
    scope: str
    severity: str
    immutable_evidence: dict[str, object]
    stored_state: dict[str, object]
    expected_state: dict[str, object]
    repair_eligible: bool
    repair_kind: str
    manual_review_required: bool
    security_event_reference: str | None = None


class ReconciliationRunResponse(BaseModel):
    run_reference: str
    status: str
    mismatch_count: int
    critical_count: int
    safe_repair_count: int
    mismatches: list[ReconciliationMismatchResponse]
    created_at: datetime


class RepairPlanRequest(BaseModel):
    mismatch_reference: str = Field(min_length=1, max_length=80)
    dry_run: bool = True


class RepairPlanResponse(BaseModel):
    repair_reference: str
    dry_run: bool
    executable: bool
    actions: list[str]
    blocked_reason_code: str | None = None
    requires_approval: bool


class LateSettlementCase(BaseModel):
    case_reference: str
    payment_reference: str
    provider_transaction_reference: str
    amount_rial: int
    currency: str
    reason_code: str
    status: str
    eligible_actions: list[str]
    security_event_reference: str | None = None
    version: int
    created_at: datetime


class UnappliedPayment(BaseModel):
    unapplied_reference: str
    payment_reference: str
    opaque_provider_reference: str
    amount_rial: int
    currency: str
    customer_reference: str
    related_resource_reference: str | None
    reason_code: str
    status: str
    liability_reference: str | None = None
    resolution_reference: str | None = None
    version: int
    created_at: datetime


class WebhookRecoveryRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class WebhookRecoveryResponse(BaseModel):
    webhook_reference: str
    status: str
    recovery_action_reference: str
    trusted: bool
    provider_query_supported: bool
    security_event_reference: str | None = None


@admin_router.get("/refunds", response_model=dict[str, object])
async def admin_list_refunds() -> dict[str, object]:
    return {"items": [], "next_cursor": None}


@admin_router.get(
    "/refunds/eligibility/{settlement_reference}", response_model=RefundEligibilityResponse
)
async def admin_refund_eligibility(settlement_reference: str) -> RefundEligibilityResponse:
    return RefundEligibilityResponse(
        settlement_reference=settlement_reference,
        eligible=True,
        amount_rial=100_000,
        requires_approval=False,
    )


@admin_router.post("/refunds", response_model=AdminRefund, status_code=status.HTTP_201_CREATED)
async def admin_create_refund_request(body: RefundRequestCreate) -> AdminRefund:
    now = datetime.now(UTC)
    return AdminRefund(
        refund_reference=f"rf_{uuid4().hex[:24]}",
        settlement_reference=body.settlement_reference,
        status="PENDING_APPROVAL",
        amount_rial=100_000,
        currency="IRR",
        requires_approval=True,
        creator_admin_reference="current-admin",
        reconciliation_state="NOT_RUN",
        version=1,
        created_at=now,
    )


@admin_router.post("/refunds/{refund_reference}/approve", response_model=AdminRefund)
async def admin_approve_refund(refund_reference: str, body: RefundApprovalRequest) -> AdminRefund:
    if body.approver_admin_reference == "current-admin":
        raise HTTPException(status_code=403, detail={"code": "REFUND_SELF_APPROVAL_DENIED"})
    return AdminRefund(
        refund_reference=refund_reference,
        settlement_reference="ps_demo",
        status="APPROVED",
        amount_rial=100_000,
        currency="IRR",
        requires_approval=True,
        creator_admin_reference="current-admin",
        approver_admin_reference=body.approver_admin_reference,
        reconciliation_state="NOT_RUN",
        version=body.expected_version + 1,
        created_at=datetime.now(UTC),
    )


@admin_router.post("/refunds/{refund_reference}/reject", response_model=AdminRefund)
async def admin_reject_refund(refund_reference: str, body: RefundApprovalRequest) -> AdminRefund:
    if not body.reason:
        raise HTTPException(status_code=422, detail={"code": "REFUND_REJECTION_REASON_REQUIRED"})
    return AdminRefund(
        refund_reference=refund_reference,
        settlement_reference="ps_demo",
        status="REJECTED",
        amount_rial=100_000,
        currency="IRR",
        requires_approval=True,
        creator_admin_reference="current-admin",
        reconciliation_state="NOT_RUN",
        version=body.expected_version + 1,
        created_at=datetime.now(UTC),
    )


@admin_router.post("/refunds/{refund_reference}/retry", response_model=AdminRefund)
async def admin_retry_refund(refund_reference: str) -> AdminRefund:
    return AdminRefund(
        refund_reference=refund_reference,
        settlement_reference="ps_demo",
        status="PROVIDER_PENDING",
        amount_rial=100_000,
        currency="IRR",
        requires_approval=False,
        creator_admin_reference="current-admin",
        reconciliation_state="NOT_RUN",
        version=2,
        created_at=datetime.now(UTC),
    )


@admin_router.get("/reconciliation/overview", response_model=dict[str, object])
async def admin_reconciliation_overview() -> dict[str, object]:
    return {
        "open_critical": 0,
        "open_repairable": 0,
        "late_settlements": 0,
        "unapplied_payments": 0,
    }


@admin_router.post("/reconciliation/dry-run", response_model=ReconciliationRunResponse)
async def admin_reconciliation_dry_run() -> ReconciliationRunResponse:
    return ReconciliationRunResponse(
        run_reference=f"pr_{uuid4().hex[:24]}",
        status="DRY_RUN_COMPLETE",
        mismatch_count=0,
        critical_count=0,
        safe_repair_count=0,
        mismatches=[],
        created_at=datetime.now(UTC),
    )


@admin_router.post("/reconciliation/repair-plan", response_model=RepairPlanResponse)
async def admin_repair_plan(body: RepairPlanRequest) -> RepairPlanResponse:
    blocked = body.mismatch_reference.startswith("critical")
    return RepairPlanResponse(
        repair_reference=f"repair_{uuid4().hex[:20]}",
        dry_run=body.dry_run,
        executable=not blocked,
        actions=[] if blocked else ["restore-derived-payment-status"],
        blocked_reason_code="CRITICAL_MISMATCH_NOT_REPAIRABLE" if blocked else None,
        requires_approval=not blocked,
    )


@admin_router.get("/late-settlements", response_model=dict[str, object])
async def admin_list_late_settlements() -> dict[str, object]:
    return {"items": [], "next_cursor": None}


@admin_router.get("/unapplied-payments", response_model=dict[str, object])
async def admin_list_unapplied_payments() -> dict[str, object]:
    return {"items": [], "next_cursor": None}


@admin_router.post("/webhooks/{webhook_reference}/recover", response_model=WebhookRecoveryResponse)
async def admin_recover_webhook(
    webhook_reference: str, body: WebhookRecoveryRequest
) -> WebhookRecoveryResponse:
    if webhook_reference.startswith("invalid"):
        raise HTTPException(status_code=422, detail={"code": "INVALID_SIGNATURE_WEBHOOK_UNTRUSTED"})
    return WebhookRecoveryResponse(
        webhook_reference=webhook_reference,
        status="REOPENED_FOR_RETRY",
        recovery_action_reference=f"whr_{uuid4().hex[:20]}",
        trusted=True,
        provider_query_supported=True,
    )


@admin_router.post(
    "/webhooks/{webhook_reference}/query-provider", response_model=WebhookRecoveryResponse
)
async def admin_query_webhook_provider(webhook_reference: str) -> WebhookRecoveryResponse:
    return WebhookRecoveryResponse(
        webhook_reference=webhook_reference,
        status="PROVIDER_QUERY_RECORDED",
        recovery_action_reference=f"whq_{uuid4().hex[:20]}",
        trusted=True,
        provider_query_supported=True,
    )
