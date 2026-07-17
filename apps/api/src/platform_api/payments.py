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
from .payment_models import PaymentMethodModel

customer_router = APIRouter(prefix="/api/customer/payments", tags=["customer-payments"])
admin_router = APIRouter(prefix="/api/admin/payments", tags=["admin-payments"])
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
    session: Session = DB_SESSION_DEPENDENCY,
) -> list[PublicPaymentMethod]:
    rows = session.execute(
        select(PaymentMethodModel)
        .where(
            PaymentMethodModel.status == "ACTIVE", PaymentMethodModel.maintenance_mode.is_(False)
        )
        .order_by(PaymentMethodModel.priority)
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


@customer_router.get("/intents/{intent_reference}")
async def get_payment_intent(intent_reference: str) -> dict[str, str]:
    return {"reference": intent_reference, "status": "REQUIRES_VERIFICATION"}


@customer_router.post("/intents/{intent_reference}/cancel")
async def cancel_payment_intent(intent_reference: str) -> dict[str, str]:
    return {"reference": intent_reference, "status": "CANCELLED"}


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
