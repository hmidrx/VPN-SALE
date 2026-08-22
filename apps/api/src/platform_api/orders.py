# pyright: reportPrivateUsage=false, reportOptionalMemberAccess=false, reportArgumentType=false, reportAttributeAccessIssue=false
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vpnsale_domain.identity import UserStatus, sanitize_metadata
from vpnsale_domain.orders import InvoiceTotals, require_order_transition

from platform_api.catalog_models import (
    CustomerPriceQuoteLineModel,
    CustomerPriceQuoteModel,
    ProductModel,
    ProductVersionModel,
)
from platform_api.config import Settings, get_settings
from platform_api.customer_auth.service import CustomerAccessTokenService
from platform_api.database import get_db_session
from platform_api.identity.models import AuditLogModel, CustomerSessionModel, UserModel
from platform_api.management import require_perm
from platform_api.order_models import (
    CheckoutIdempotencyRecordModel,
    CheckoutSessionModel,
    InvoiceLineModel,
    InvoiceModel,
    OrderCancellationModel,
    OrderItemModel,
    OrderModel,
    OrderTimelineEventModel,
    TransactionalOutboxModel,
    WalletPaymentModel,
)
from platform_api.wallet import (
    _bucket,
    _ensure_wallet,
    _projection,
    _system_account,
    _wallet_account,
)
from platform_api.wallet_models import JournalEntryModel, LedgerPostingModel, WalletReservationModel

customer_router = APIRouter(prefix="/api/v1/customer", tags=["customer-orders"])
admin_router = APIRouter(prefix="/api/v1/admin/management/orders", tags=["admin-orders"])
admin_invoice_router = APIRouter(
    prefix="/api/v1/admin/management/invoices", tags=["admin-invoices"]
)
admin_checkout_router = APIRouter(
    prefix="/api/v1/admin/management/checkout", tags=["admin-checkout"]
)
admin_wallet_payment_router = APIRouter(
    prefix="/api/v1/admin/management/wallet-payments", tags=["admin-wallet-payments"]
)
admin_wallet_reservation_router = APIRouter(
    prefix="/api/v1/admin/management/wallet-reservations", tags=["admin-wallet-reservations"]
)
admin_outbox_router = APIRouter(
    prefix="/api/v1/admin/management/fulfillment-outbox", tags=["admin-fulfillment-outbox"]
)
admin_commerce_router = APIRouter(
    prefix="/api/v1/admin/management/commerce", tags=["admin-commerce"]
)


class ApiError(BaseModel):
    code: str
    message_key: str
    correlation_id: str


class CheckoutRequest(BaseModel):
    quote_reference: str = Field(min_length=8, max_length=80)
    payment_method: str = Field(pattern="^WALLET$")
    accepted_policy_version: str | None = Field(default=None, max_length=80)


class CancelRequest(BaseModel):
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    reason: str = Field(min_length=1, max_length=240)


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _err(status: int, request: Request, code: str) -> HTTPException:
    return HTTPException(
        status,
        detail=ApiError(
            code=code, message_key=f"orders.{code}", correlation_id=_cid(request)
        ).model_dump(),
    )


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _ref(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(16).replace('-', '').replace('_', '')[:22]}"


def _customer_from_token(
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _err(401, request, "UNAUTHENTICATED")
    try:
        claims = CustomerAccessTokenService(settings).validate(authorization.split(" ", 1)[1])
    except ValueError as exc:
        raise _err(401, request, "UNAUTHENTICATED") from exc
    sess = db.get(CustomerSessionModel, claims["session_id"])
    user = db.get(UserModel, sess.user_id) if sess else None
    if not sess or sess.revoked_at or sess.consumed_at or not user:
        raise _err(401, request, "UNAUTHENTICATED")
    if user.status != UserStatus.ACTIVE.value:
        raise _err(403, request, "ACCOUNT_CHECKOUT_DENIED")
    return sess.user_id


def _audit(
    db: Session,
    actor_type: str,
    actor_id: str | None,
    code: str,
    target_type: str,
    target_id: str | None,
    request: Request,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLogModel(
            actor_type=actor_type,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            metadata_=sanitize_metadata(metadata or {}),
        )
    )


def _timeline(
    db: Session,
    order_id: str,
    code: str,
    actor_type: str,
    actor_reference: str | None,
    request: Request,
    metadata: dict[str, object] | None = None,
) -> None:
    seq = (
        db.scalar(
            select(func.count())
            .select_from(OrderTimelineEventModel)
            .where(OrderTimelineEventModel.order_id == order_id)
        )
        or 0
    ) + 1
    db.add(
        OrderTimelineEventModel(
            order_id=order_id,
            sequence=seq,
            event_code=code,
            actor_type=actor_type,
            actor_reference=actor_reference,
            correlation_id=_cid(request),
            safe_metadata=sanitize_metadata(metadata or {}),
            occurred_at=datetime.now(UTC),
        )
    )


def _order_view(db: Session, order: OrderModel) -> dict[str, Any]:
    inv = db.scalar(select(InvoiceModel).where(InvoiceModel.order_id == order.id))
    checkout = db.scalar(
        select(CheckoutSessionModel).where(CheckoutSessionModel.order_id == order.id)
    )
    payment = db.scalar(select(WalletPaymentModel).where(WalletPaymentModel.order_id == order.id))
    reservation = db.get(WalletReservationModel, payment.reservation_id) if payment else None
    return {
        "order_reference": order.reference,
        "quote_reference": order.quote_reference,
        "checkout_reference": checkout.reference if checkout else None,
        "invoice_reference": inv.reference if inv else None,
        "wallet_payment_reference": payment.reference if payment else None,
        "reservation_reference": reservation.opaque_reference if reservation else None,
        "customer": {"customer_id": order.customer_id},
        "status": order.status,
        "financial_status": order.financial_status,
        "fulfillment_status": order.fulfillment_status,
        "subtotal_rial": order.subtotal_rial,
        "adjustment_total_rial": order.adjustment_total_rial,
        "final_amount_rial": order.final_amount_rial,
        "paid_total_rial": inv.paid_total_rial if inv else 0,
        "refunded_total_rial": payment.amount_rial
        if payment and payment.status == "REFUNDED"
        else 0,
        "payment_method": order.payment_method,
        "currency": order.currency,
        "created_at": order.created_at.isoformat(),
        "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        "cancelled_at": order.cancelled_at.isoformat() if order.cancelled_at else None,
        "version": order.version,
        "snapshot": order.snapshot,
        "cancellation_eligibility": {
            "cancellable": order.fulfillment_status != "SUCCEEDED"
            and order.status not in {"CANCELLED", "REFUNDED"},
            "consequence": "compensating_wallet_refund"
            if payment and payment.status == "CAPTURED"
            else "reservation_release",
            "active_reservation_amount_rial": reservation.amount_rial
            if reservation and reservation.status == "ACTIVE"
            else 0,
            "reason_codes": ["CUSTOMER_REQUEST", "RISK_REVIEW", "OPERATOR_CORRECTION"],
        },
        "reconciliation_health": "UNKNOWN",
    }


def _invoice_view(db: Session, invoice: InvoiceModel) -> dict[str, Any]:
    lines = db.scalars(
        select(InvoiceLineModel)
        .where(InvoiceLineModel.invoice_id == invoice.id)
        .order_by(InvoiceLineModel.position)
    ).all()
    return {
        "invoice_reference": invoice.reference,
        "order_reference": db.get(OrderModel, invoice.order_id).reference,
        "customer": {"customer_id": invoice.customer_id},
        "status": invoice.status,
        "currency": invoice.currency,
        "subtotal_rial": invoice.subtotal_rial,
        "adjustment_total_rial": invoice.adjustment_total_rial,
        "discount_total_rial": invoice.discount_total_rial,
        "tax_total_rial": invoice.tax_total_rial,
        "payable_total_rial": invoice.payable_total_rial,
        "paid_total_rial": invoice.paid_total_rial,
        "issued_at": invoice.issued_at.isoformat(),
        "due_at": invoice.due_at.isoformat(),
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "cancelled_at": invoice.cancelled_at.isoformat() if invoice.cancelled_at else None,
        "refunded_at": invoice.cancelled_at.isoformat()
        if invoice.status == "REFUNDED" and invoice.cancelled_at
        else None,
        "invoice_version": invoice.invoice_version,
        "reconciliation_health": "UNKNOWN",
        "lines": [
            {
                "line_type": line.line_type,
                "description": line.description,
                "quantity": line.quantity,
                "unit_amount_rial": line.unit_amount_rial,
                "line_subtotal_rial": line.line_subtotal_rial,
                "position": line.position,
                "product_id": line.product_id,
                "product_version_id": line.product_version_id,
                "safe_metadata": line.safe_metadata,
            }
            for line in lines
        ],
    }


def _reserve_wallet(
    db: Session, customer_id: str, amount: int, related: str, request: Request
) -> tuple[str, str]:
    wallet = _ensure_wallet(db, customer_id)
    if wallet.status == "FROZEN":
        raise _err(409, request, "WALLET_FROZEN")
    proj = _projection(db, wallet.id, lock=True)
    if proj.available_balance_rial < amount:
        raise _err(409, request, "INSUFFICIENT_AVAILABLE_BALANCE")
    now = datetime.now(UTC)
    reservation = WalletReservationModel(
        wallet_id=wallet.id,
        customer_id=customer_id,
        amount_rial=amount,
        currency="IRR",
        status="ACTIVE",
        purpose_code="ORDER_CHECKOUT",
        opaque_reference=related,
        safe_metadata={"purpose": "order_checkout"},
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(reservation)
    db.flush()
    proj.reserved_balance_rial += amount
    proj.available_balance_rial = proj.posted_balance_rial - proj.reserved_balance_rial
    proj.version += 1
    return wallet.id, reservation.id


def _release_reservation(
    db: Session, reservation: WalletReservationModel, status: str = "RELEASED"
) -> None:
    if reservation.status != "ACTIVE":
        return
    proj = _projection(db, reservation.wallet_id, lock=True)
    reservation.status = status
    reservation.released_at = datetime.now(UTC)
    proj.reserved_balance_rial -= reservation.amount_rial
    proj.available_balance_rial = proj.posted_balance_rial - proj.reserved_balance_rial
    proj.version += 1


def _capture_reservation(
    db: Session,
    order: OrderModel,
    invoice: InvoiceModel,
    payment: WalletPaymentModel,
    reservation: WalletReservationModel,
    request: Request,
) -> str:
    if payment.status == "CAPTURED" and payment.capture_journal_id:
        return payment.capture_journal_id
    if reservation.status != "ACTIVE" or reservation.customer_id != order.customer_id:
        raise _err(409, request, "RESERVATION_NOT_ACTIVE")
    wallet_acct = _wallet_account(db, _ensure_wallet(db, order.customer_id), "CASH")
    clearing = _system_account(db, "PAYMENT_CLEARING")
    now = datetime.now(UTC)
    journal = JournalEntryModel(
        operation_code="ORDER_WALLET_CAPTURE",
        status="POSTED",
        currency="IRR",
        wallet_id=reservation.wallet_id,
        actor_type="customer",
        actor_id=order.customer_id,
        correlation_id=_cid(request),
        description_code="ORDER_WALLET_PAYMENT",
        safe_metadata={"order_reference": order.reference, "invoice_reference": invoice.reference},
        occurred_at=now,
        posted_at=now,
    )
    db.add(journal)
    db.flush()
    db.add_all(
        [
            LedgerPostingModel(
                journal_entry_id=journal.id,
                ledger_account_id=wallet_acct.id,
                direction="DEBIT",
                amount_rial=payment.amount_rial,
                posting_order=1,
                purpose_code="ORDER_WALLET_CAPTURE",
            ),
            LedgerPostingModel(
                journal_entry_id=journal.id,
                ledger_account_id=clearing.id,
                direction="CREDIT",
                amount_rial=payment.amount_rial,
                posting_order=2,
                purpose_code="ORDER_WALLET_CAPTURE",
            ),
        ]
    )
    proj = _projection(db, reservation.wallet_id, lock=True)
    proj.posted_balance_rial -= payment.amount_rial
    proj.reserved_balance_rial -= payment.amount_rial
    proj.available_balance_rial = proj.posted_balance_rial - proj.reserved_balance_rial
    proj.version += 1
    cash = _bucket(db, reservation.wallet_id, "CASH")
    cash.balance_rial -= payment.amount_rial
    reservation.status = "CAPTURED"
    reservation.captured_at = now
    payment.status = "CAPTURED"
    payment.capture_journal_id = journal.id
    payment.completed_at = now
    return journal.id


def _post_refund(
    db: Session, order: OrderModel, payment: WalletPaymentModel, request: Request | str
) -> str:
    if payment.refund_journal_id:
        return payment.refund_journal_id
    wallet = db.get(
        __import__("platform_api.wallet_models", fromlist=["WalletModel"]).WalletModel,
        payment.wallet_id,
    )
    wallet_acct = _wallet_account(db, wallet, "REFUND")
    clearing = _system_account(db, "REFUND_CLEARING")
    now = datetime.now(UTC)
    journal = JournalEntryModel(
        operation_code="ORDER_WALLET_REFUND",
        status="POSTED",
        currency="IRR",
        wallet_id=payment.wallet_id,
        actor_type="system",
        actor_id=None,
        correlation_id=_cid(request) if isinstance(request, Request) else request,
        description_code="ORDER_CANCELLATION_REFUND",
        safe_metadata={"order_reference": order.reference},
        occurred_at=now,
        posted_at=now,
    )
    db.add(journal)
    db.flush()
    db.add_all(
        [
            LedgerPostingModel(
                journal_entry_id=journal.id,
                ledger_account_id=clearing.id,
                direction="DEBIT",
                amount_rial=payment.amount_rial,
                posting_order=1,
                purpose_code="ORDER_WALLET_REFUND",
            ),
            LedgerPostingModel(
                journal_entry_id=journal.id,
                ledger_account_id=wallet_acct.id,
                direction="CREDIT",
                amount_rial=payment.amount_rial,
                posting_order=2,
                purpose_code="ORDER_WALLET_REFUND",
            ),
        ]
    )
    proj = _projection(db, payment.wallet_id, lock=True)
    proj.posted_balance_rial += payment.amount_rial
    proj.available_balance_rial = proj.posted_balance_rial - proj.reserved_balance_rial
    proj.version += 1
    _bucket(db, payment.wallet_id, "REFUND").balance_rial += payment.amount_rial
    payment.status = "REFUNDED"
    payment.refund_journal_id = journal.id
    return journal.id


def compensate_failed_fulfillment(
    db: Session, order: OrderModel, correlation_id: str, reason_code: str
) -> str:
    """Authoritative, idempotent compensation used by HTTP cancellation and workers."""
    payment = db.scalar(
        select(WalletPaymentModel).where(WalletPaymentModel.order_id == order.id).with_for_update()
    )
    if payment is None or payment.status not in {"CAPTURED", "REFUNDED"}:
        raise ValueError("captured wallet payment required for fulfillment compensation")
    refund_id = _post_refund(db, order, payment, correlation_id)
    now = datetime.now(UTC)
    order.status = "REFUNDED"
    order.financial_status = "REFUNDED"
    order.fulfillment_status = "FAILED"
    order.cancelled_at = order.cancelled_at or now
    invoice = db.scalar(select(InvoiceModel).where(InvoiceModel.order_id == order.id))
    if invoice is not None:
        invoice.status = "REFUNDED"
    existing = db.scalar(
        select(OrderCancellationModel).where(
            OrderCancellationModel.order_id == order.id,
            OrderCancellationModel.reason_code == reason_code,
        )
    )
    if existing is None:
        db.add(
            OrderCancellationModel(
                order_id=order.id,
                actor_type="system",
                actor_reference="fulfillment-worker",
                reason_code=reason_code,
                reason="Definitive provider provisioning rejection",
                refund_journal_id=refund_id,
                created_at=now,
            )
        )
    return refund_id


@customer_router.post("/checkout")
def create_checkout(
    body: CheckoutRequest,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=120)],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    quote = db.scalar(
        select(CustomerPriceQuoteModel)
        .where(CustomerPriceQuoteModel.reference == body.quote_reference)
        .with_for_update()
    )
    if not quote:
        raise _err(404, request, "QUOTE_NOT_FOUND")
    if quote.customer_id != customer_id:
        raise _err(403, request, "QUOTE_NOT_OWNED")
    fp = _hash(f"checkout|{quote.id}|{body.payment_method}|{body.accepted_policy_version or ''}")
    idem = db.scalar(
        select(CheckoutIdempotencyRecordModel)
        .where(
            CheckoutIdempotencyRecordModel.customer_id == customer_id,
            CheckoutIdempotencyRecordModel.quote_id == quote.id,
            CheckoutIdempotencyRecordModel.operation_type == "CREATE_CHECKOUT",
            CheckoutIdempotencyRecordModel.payment_method == body.payment_method,
            CheckoutIdempotencyRecordModel.key_hash == _hash(idempotency_key),
        )
        .with_for_update()
    )
    if idem and idem.request_fingerprint != fp:
        raise _err(409, request, "IDEMPOTENCY_CONFLICT")
    if idem and idem.result_snapshot:
        return idem.result_snapshot
    if quote.status != "ACTIVE":
        raise _err(409, request, "QUOTE_ALREADY_CONSUMED")
    if quote.expires_at.replace(tzinfo=UTC) <= now:
        raise _err(409, request, "QUOTE_EXPIRED")
    existing = db.scalar(select(OrderModel).where(OrderModel.quote_id == quote.id))
    if existing:
        raise _err(409, request, "QUOTE_ALREADY_CONSUMED")
    product = db.get(ProductModel, quote.product_id)
    version = db.get(ProductVersionModel, quote.product_version_id)
    if not product or not version:
        raise _err(409, request, "PRODUCT_UNAVAILABLE")
    InvoiceTotals(quote.subtotal_minor, 0, 0, 0, quote.final_amount_minor).validate()
    order = OrderModel(
        reference=_ref("ord"),
        customer_id=customer_id,
        quote_id=quote.id,
        quote_reference=quote.reference,
        status="PAYMENT_RESERVED",
        financial_status="RESERVED",
        fulfillment_status="NOT_READY",
        payment_method="WALLET",
        currency="IRR",
        subtotal_rial=quote.subtotal_minor,
        adjustment_total_rial=0,
        final_amount_rial=quote.final_amount_minor,
        snapshot={
            "quote_reference": quote.reference,
            "product_id": quote.product_id,
            "product_version_id": quote.product_version_id,
            "product_machine_code": product.machine_code,
            "product_label_snapshot": product.localizations,
            "plan_type": version.product_type,
            "operation": quote.operation,
            "selected_options": quote.selected_options,
            "fulfillment_requirement_schema_version": "catalog.v1",
            "fulfillment_requirement_snapshot": version.fulfillment_requirements_snapshot,
            "pricing_engine_version": quote.pricing_engine_version,
            "quote_issued_at": quote.issued_at.isoformat(),
            "quote_expires_at": quote.expires_at.isoformat(),
        },
        created_at=now,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItemModel(
            order_id=order.id,
            product_id=quote.product_id,
            product_version_id=quote.product_version_id,
            product_machine_code=product.machine_code,
            snapshot=order.snapshot,
            position=1,
        )
    )
    inv = InvoiceModel(
        reference=_ref("inv"),
        customer_id=customer_id,
        order_id=order.id,
        status="PAYMENT_RESERVED",
        currency="IRR",
        subtotal_rial=quote.subtotal_minor,
        adjustment_total_rial=0,
        discount_total_rial=0,
        tax_total_rial=0,
        payable_total_rial=quote.final_amount_minor,
        paid_total_rial=0,
        issued_at=now,
        due_at=now + timedelta(minutes=15),
    )
    db.add(inv)
    db.flush()
    lines = db.scalars(
        select(CustomerPriceQuoteLineModel)
        .where(CustomerPriceQuoteLineModel.quote_id == quote.id)
        .order_by(CustomerPriceQuoteLineModel.display_order)
    ).all()
    for idx, line in enumerate(lines or [], 1):
        db.add(
            InvoiceLineModel(
                invoice_id=inv.id,
                line_type="QUOTE_COMPONENT",
                product_id=quote.product_id,
                product_version_id=quote.product_version_id,
                description=line.label,
                quantity=1,
                unit_amount_rial=line.amount_minor,
                line_subtotal_rial=line.amount_minor,
                position=idx,
                safe_metadata={"component_code": line.component_code},
            )
        )
    wallet_id, reservation_id = _reserve_wallet(
        db, customer_id, quote.final_amount_minor, order.reference, request
    )
    checkout = CheckoutSessionModel(
        reference=_ref("chk"),
        customer_id=customer_id,
        quote_id=quote.id,
        order_id=order.id,
        payment_method="WALLET",
        status="FUNDS_RESERVED",
        amount_rial=quote.final_amount_minor,
        currency="IRR",
        wallet_reservation_id=reservation_id,
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )
    db.add(checkout)
    db.flush()
    db.add(
        WalletPaymentModel(
            reference=_ref("wpy"),
            order_id=order.id,
            invoice_id=inv.id,
            wallet_id=wallet_id,
            reservation_id=reservation_id,
            amount_rial=quote.final_amount_minor,
            currency="IRR",
            status="RESERVED",
            created_at=now,
        )
    )
    if not idem:
        idem = CheckoutIdempotencyRecordModel(
            customer_id=customer_id,
            quote_id=quote.id,
            operation_type="CREATE_CHECKOUT",
            payment_method="WALLET",
            key_hash=_hash(idempotency_key),
            request_fingerprint=fp,
            expires_at=now + timedelta(days=14),
        )
        db.add(idem)
    idem.checkout_id = checkout.id
    result = {
        "checkout": {
            "checkout_reference": checkout.reference,
            "status": checkout.status,
            "reservation_amount_rial": checkout.amount_rial,
            "expires_at": checkout.expires_at.isoformat(),
        },
        "order": _order_view(db, order),
        "invoice": _invoice_view(db, inv),
    }
    idem.result_snapshot = result
    _timeline(db, order.id, "ORDER_CREATED", "customer", customer_id, request)
    _timeline(db, order.id, "INVOICE_ISSUED", "system", None, request)
    _timeline(db, order.id, "WALLET_RESERVATION_CREATED", "system", None, request)
    _audit(
        db,
        "customer",
        customer_id,
        "checkout.created",
        "order",
        order.id,
        request,
        {"order_reference": order.reference},
    )
    return result


@customer_router.get("/checkout/{checkout_reference}")
def get_checkout(
    checkout_reference: str,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    checkout = db.scalar(
        select(CheckoutSessionModel).where(CheckoutSessionModel.reference == checkout_reference)
    )
    if not checkout or checkout.customer_id != customer_id:
        raise _err(404, request, "CHECKOUT_NOT_FOUND")
    order = db.get(OrderModel, checkout.order_id)
    invoice = db.scalar(select(InvoiceModel).where(InvoiceModel.order_id == checkout.order_id))
    if not order or not invoice:
        raise _err(409, request, "CHECKOUT_INCONSISTENT")
    return {
        "checkout": {
            "checkout_reference": checkout.reference,
            "status": checkout.status,
            "reservation_amount_rial": checkout.amount_rial,
            "expires_at": checkout.expires_at.isoformat(),
        },
        "order": _order_view(db, order),
        "invoice": _invoice_view(db, invoice),
    }


@customer_router.post("/checkout/{checkout_reference}/confirm")
def confirm_checkout(
    checkout_reference: str,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    checkout = db.scalar(
        select(CheckoutSessionModel)
        .where(CheckoutSessionModel.reference == checkout_reference)
        .with_for_update()
    )
    if not checkout or checkout.customer_id != customer_id:
        raise _err(404, request, "CHECKOUT_NOT_FOUND")
    order = db.get(OrderModel, checkout.order_id)
    invoice = db.scalar(select(InvoiceModel).where(InvoiceModel.order_id == order.id))
    payment = db.scalar(select(WalletPaymentModel).where(WalletPaymentModel.order_id == order.id))
    reservation = db.get(WalletReservationModel, checkout.wallet_reservation_id)
    if checkout.status == "COMPLETED":
        return {
            "checkout": {"checkout_reference": checkout.reference, "status": checkout.status},
            "order": _order_view(db, order),
            "invoice": _invoice_view(db, invoice),
        }
    if checkout.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise _err(409, request, "CHECKOUT_EXPIRED")
    _capture_reservation(db, order, invoice, payment, reservation, request)
    now = datetime.now(UTC)
    require_order_transition(order.status, "PAID")
    order.status = "PAID"
    order.financial_status = "PAID"
    order.paid_at = now
    invoice.status = "PAID"
    invoice.paid_total_rial = invoice.payable_total_rial
    invoice.paid_at = now
    require_order_transition(order.status, "READY_FOR_FULFILLMENT")
    order.status = "READY_FOR_FULFILLMENT"
    order.fulfillment_status = "READY"
    checkout.status = "COMPLETED"
    checkout.completed_at = now
    db.add(
        TransactionalOutboxModel(
            event_key=f"order.ready:{order.id}",
            event_type="order.ready_for_fulfillment.v1",
            status="PENDING",
            payload={
                "event_version": 1,
                "order_id": order.id,
                "order_reference": order.reference,
                "customer_id": customer_id,
                "product_version_id": order.snapshot.get("product_version_id"),
                "selected_options": order.snapshot.get("selected_options"),
                "fulfillment_requirement_schema_version": order.snapshot.get(
                    "fulfillment_requirement_schema_version"
                ),
                "correlation_id": _cid(request),
                "occurred_at": now.isoformat(),
            },
            available_at=now,
        )
    )
    _timeline(db, order.id, "WALLET_PAYMENT_CAPTURED", "system", None, request)
    _timeline(db, order.id, "ORDER_READY_FOR_FULFILLMENT", "system", None, request)
    _audit(
        db,
        "customer",
        customer_id,
        "checkout.confirmed",
        "order",
        order.id,
        request,
        {"order_reference": order.reference},
    )
    return {
        "checkout": {"checkout_reference": checkout.reference, "status": checkout.status},
        "order": _order_view(db, order),
        "invoice": _invoice_view(db, invoice),
    }


def _cancel(
    db: Session,
    checkout: CheckoutSessionModel | None,
    order: OrderModel,
    actor_type: str,
    actor_ref: str,
    reason_code: str,
    reason: str,
    request: Request,
) -> dict[str, Any]:
    invoice = db.scalar(select(InvoiceModel).where(InvoiceModel.order_id == order.id))
    payment = db.scalar(select(WalletPaymentModel).where(WalletPaymentModel.order_id == order.id))
    reservation = (
        db.get(WalletReservationModel, checkout.wallet_reservation_id)
        if checkout and checkout.wallet_reservation_id
        else None
    )
    if order.status in {"CANCELLED", "REFUNDED"}:
        return _order_view(db, order)
    now = datetime.now(UTC)
    refund_id = None
    if payment and payment.status == "CAPTURED":
        refund_id = _post_refund(db, order, payment, request)
        order.status = "REFUNDED"
        order.financial_status = "REFUNDED"
        invoice.status = "REFUNDED"
    else:
        if reservation:
            _release_reservation(db, reservation)
        order.status = "CANCELLED"
        order.financial_status = "UNPAID"
        order.fulfillment_status = "CANCELLED"
        invoice.status = "CANCELLED"
        invoice.cancelled_at = now
    order.cancelled_at = now
    if checkout:
        checkout.status = "CANCELLED"
        checkout.cancelled_at = now
    db.add(
        OrderCancellationModel(
            order_id=order.id,
            actor_type=actor_type,
            actor_reference=actor_ref,
            reason_code=reason_code,
            reason=reason,
            refund_journal_id=refund_id,
            created_at=now,
        )
    )
    outbox = db.scalar(
        select(TransactionalOutboxModel)
        .where(
            TransactionalOutboxModel.event_key == f"order.ready:{order.id}",
            TransactionalOutboxModel.status == "PENDING",
        )
        .with_for_update()
    )
    if outbox:
        outbox.status = "FAILED"
        outbox.failure_category = "ORDER_CANCELLED"
    _timeline(
        db,
        order.id,
        "ORDER_CANCELLED",
        actor_type,
        actor_ref,
        request,
        {"reason_code": reason_code},
    )
    return _order_view(db, order)


@customer_router.post("/checkout/{checkout_reference}/cancel")
def cancel_checkout(
    checkout_reference: str,
    body: CancelRequest,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    checkout = db.scalar(
        select(CheckoutSessionModel)
        .where(CheckoutSessionModel.reference == checkout_reference)
        .with_for_update()
    )
    if not checkout or checkout.customer_id != customer_id:
        raise _err(404, request, "CHECKOUT_NOT_FOUND")
    return {
        "order": _cancel(
            db,
            checkout,
            db.get(OrderModel, checkout.order_id),
            "customer",
            customer_id,
            body.reason_code,
            body.reason,
            request,
        )
    }


@customer_router.get("/orders")
def list_orders(
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> dict[str, Any]:
    rows = db.scalars(
        select(OrderModel)
        .where(OrderModel.customer_id == customer_id)
        .order_by(OrderModel.created_at.desc())
        .limit(min(max(limit, 1), 100))
    ).all()
    return {"items": [_order_view(db, r) for r in rows], "next_cursor": None}


@customer_router.get("/orders/{order_reference}")
def order_detail(
    order_reference: str,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    order = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
    if not order or order.customer_id != customer_id:
        raise _err(404, request, "ORDER_NOT_FOUND")
    return _order_view(db, order)


@customer_router.get("/orders/{order_reference}/timeline")
def order_timeline(
    order_reference: str,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    order = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
    if not order or order.customer_id != customer_id:
        raise _err(404, request, "ORDER_NOT_FOUND")
    rows = db.scalars(
        select(OrderTimelineEventModel)
        .where(OrderTimelineEventModel.order_id == order.id)
        .order_by(OrderTimelineEventModel.sequence)
    ).all()
    return {
        "items": [
            {
                "event_code": r.event_code,
                "occurred_at": r.occurred_at.isoformat(),
                "actor_type": r.actor_type,
                "actor_reference": r.actor_reference,
                "correlation_id": r.correlation_id,
                "metadata": r.safe_metadata,
            }
            for r in rows
        ]
    }


@customer_router.get("/invoices")
def list_invoices(
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> dict[str, Any]:
    rows = db.scalars(
        select(InvoiceModel)
        .where(InvoiceModel.customer_id == customer_id)
        .order_by(InvoiceModel.issued_at.desc())
        .limit(min(max(limit, 1), 100))
    ).all()
    return {"items": [_invoice_view(db, r) for r in rows], "next_cursor": None}


@customer_router.get("/invoices/{invoice_reference}")
def invoice_detail(
    invoice_reference: str,
    customer_id: Annotated[str, Depends(_customer_from_token)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    inv = db.scalar(select(InvoiceModel).where(InvoiceModel.reference == invoice_reference))
    if not inv or inv.customer_id != customer_id:
        raise _err(404, request, "INVOICE_NOT_FOUND")
    return _invoice_view(db, inv)


@admin_router.get("")
def admin_orders(
    _: Annotated[object, Depends(require_perm("orders.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    status: str | None = None,
    customer_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    stmt = select(OrderModel).order_by(OrderModel.created_at.desc()).limit(min(max(limit, 1), 100))
    if status:
        stmt = stmt.where(OrderModel.status == status)
    if customer_id:
        stmt = stmt.where(OrderModel.customer_id == customer_id)
    return {"items": [_order_view(db, r) for r in db.scalars(stmt).all()], "next_cursor": None}


@admin_router.get("/{order_reference}")
def admin_order_detail(
    order_reference: str,
    _: Annotated[object, Depends(require_perm("orders.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    order = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
    if not order:
        raise _err(404, request, "ORDER_NOT_FOUND")
    return _order_view(db, order)


@admin_router.get("/{order_reference}/timeline")
def admin_order_timeline(
    order_reference: str,
    _: Annotated[object, Depends(require_perm("orders.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    order = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
    if not order:
        raise _err(404, request, "ORDER_NOT_FOUND")
    rows = db.scalars(
        select(OrderTimelineEventModel)
        .where(OrderTimelineEventModel.order_id == order.id)
        .order_by(OrderTimelineEventModel.sequence)
    ).all()
    return {
        "items": [
            {
                "event_code": r.event_code,
                "occurred_at": r.occurred_at.isoformat(),
                "actor_type": r.actor_type,
                "actor_reference": r.actor_reference,
                "correlation_id": r.correlation_id,
                "metadata": r.safe_metadata,
            }
            for r in rows
        ]
    }


@admin_router.post("/{order_reference}/cancel")
def admin_cancel_order(
    order_reference: str,
    body: CancelRequest,
    admin: Annotated[Any, Depends(require_perm("orders.cancel"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    order = db.scalar(
        select(OrderModel).where(OrderModel.reference == order_reference).with_for_update()
    )
    if not order:
        raise _err(404, request, "ORDER_NOT_FOUND")
    checkout = db.scalar(
        select(CheckoutSessionModel)
        .where(CheckoutSessionModel.order_id == order.id)
        .with_for_update()
    )
    return {
        "order": _cancel(
            db, checkout, order, "admin", admin.id, body.reason_code, body.reason, request
        )
    }


@admin_router.post("/{order_reference}/reconciliation")
def admin_order_reconciliation(
    order_reference: str,
    _: Annotated[object, Depends(require_perm("ledger.reconcile"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    order = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
    if not order:
        raise _err(404, request, "ORDER_NOT_FOUND")
    invoice = db.scalar(select(InvoiceModel).where(InvoiceModel.order_id == order.id))
    payment = db.scalar(select(WalletPaymentModel).where(WalletPaymentModel.order_id == order.id))
    outbox = db.scalar(
        select(TransactionalOutboxModel).where(
            TransactionalOutboxModel.event_key == f"order.ready:{order.id}"
        )
    )
    mismatches: list[str] = []
    if invoice and invoice.payable_total_rial != order.final_amount_rial:
        mismatches.append("ORDER_INVOICE_AMOUNT_MISMATCH")
    if order.financial_status == "PAID" and (not payment or payment.status != "CAPTURED"):
        mismatches.append("PAID_ORDER_MISSING_CAPTURE")
    if order.fulfillment_status == "READY" and not outbox:
        mismatches.append("READY_ORDER_MISSING_OUTBOX")
    return {
        "order_reference": order.reference,
        "severity": "CRITICAL" if mismatches else "CLEAN",
        "checked_at": datetime.now(UTC).isoformat(),
        "mismatch_codes": mismatches,
        "recommended_action": "inspect_audit_security" if mismatches else "no_action",
        "order_payable_total_rial": order.final_amount_rial,
        "invoice_payable_total_rial": invoice.payable_total_rial if invoice else None,
        "invoice_paid_total_rial": invoice.paid_total_rial if invoice else None,
        "wallet_capture_amount_rial": payment.amount_rial
        if payment and payment.status == "CAPTURED"
        else 0,
        "wallet_refund_amount_rial": payment.amount_rial
        if payment and payment.status == "REFUNDED"
        else 0,
        "order_status": order.status,
        "financial_status": order.financial_status,
        "fulfillment_status": order.fulfillment_status,
        "outbox_readiness_state": outbox.status if outbox else "MISSING",
    }


@admin_invoice_router.get("")
def admin_invoices(
    _: Annotated[object, Depends(require_perm("invoices.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    status: str | None = None,
    order_reference: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    stmt = (
        select(InvoiceModel).order_by(InvoiceModel.issued_at.desc()).limit(min(max(limit, 1), 100))
    )
    if status:
        stmt = stmt.where(InvoiceModel.status == status)
    if order_reference:
        order = db.scalar(select(OrderModel).where(OrderModel.reference == order_reference))
        stmt = stmt.where(InvoiceModel.order_id == (order.id if order else ""))
    return {"items": [_invoice_view(db, r) for r in db.scalars(stmt).all()], "next_cursor": None}


@admin_invoice_router.get("/{invoice_reference}")
def admin_invoice_detail(
    invoice_reference: str,
    _: Annotated[object, Depends(require_perm("invoices.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    inv = db.scalar(select(InvoiceModel).where(InvoiceModel.reference == invoice_reference))
    if not inv:
        raise _err(404, request, "INVOICE_NOT_FOUND")
    return _invoice_view(db, inv)


@admin_commerce_router.get("/overview")
def admin_commerce_overview(
    _: Annotated[object, Depends(require_perm("orders.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    return {
        "supported_metrics": {
            "reserved_payment_orders": db.scalar(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.financial_status == "RESERVED")
            )
            or 0,
            "paid_orders": db.scalar(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.financial_status == "PAID")
            )
            or 0,
            "ready_for_fulfillment_orders": db.scalar(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.fulfillment_status == "READY")
            )
            or 0,
            "cancelled_orders": db.scalar(
                select(func.count()).select_from(OrderModel).where(OrderModel.status == "CANCELLED")
            )
            or 0,
            "refunded_orders": db.scalar(
                select(func.count())
                .select_from(OrderModel)
                .where(OrderModel.financial_status == "REFUNDED")
            )
            or 0,
            "failed_fulfillment_outbox_events": db.scalar(
                select(func.count())
                .select_from(TransactionalOutboxModel)
                .where(TransactionalOutboxModel.status == "FAILED")
            )
            or 0,
        }
    }


@admin_checkout_router.get("/{checkout_reference}")
def admin_checkout_detail(
    checkout_reference: str,
    _: Annotated[object, Depends(require_perm("checkout.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    checkout = db.scalar(
        select(CheckoutSessionModel).where(CheckoutSessionModel.reference == checkout_reference)
    )
    if not checkout:
        raise _err(404, request, "CHECKOUT_NOT_FOUND")
    order = db.get(OrderModel, checkout.order_id)
    reservation = (
        db.get(WalletReservationModel, checkout.wallet_reservation_id)
        if checkout.wallet_reservation_id
        else None
    )
    return {
        "checkout_reference": checkout.reference,
        "customer": {"customer_id": checkout.customer_id},
        "quote_reference": order.quote_reference if order else None,
        "order_reference": order.reference if order else None,
        "payment_method": checkout.payment_method,
        "status": checkout.status,
        "amount_rial": checkout.amount_rial,
        "currency": checkout.currency,
        "reservation_reference": reservation.opaque_reference if reservation else None,
        "created_at": checkout.created_at.isoformat(),
        "expires_at": checkout.expires_at.isoformat(),
        "completed_at": checkout.completed_at.isoformat() if checkout.completed_at else None,
        "cancelled_at": checkout.cancelled_at.isoformat() if checkout.cancelled_at else None,
        "version": checkout.version,
        "failure_code": None,
        "idempotency_outcome": "stored_without_raw_key",
    }


@admin_wallet_payment_router.get("/{payment_reference}")
def admin_wallet_payment_detail(
    payment_reference: str,
    _: Annotated[object, Depends(require_perm("wallets.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    payment = db.scalar(
        select(WalletPaymentModel).where(WalletPaymentModel.reference == payment_reference)
    )
    if not payment:
        raise _err(404, request, "WALLET_PAYMENT_NOT_FOUND")
    order = db.get(OrderModel, payment.order_id)
    invoice = db.get(InvoiceModel, payment.invoice_id)
    reservation = db.get(WalletReservationModel, payment.reservation_id)
    return {
        "wallet_payment_reference": payment.reference,
        "order_reference": order.reference if order else None,
        "invoice_reference": invoice.reference if invoice else None,
        "customer": {"customer_id": order.customer_id if order else None},
        "payment_method": "WALLET",
        "amount_rial": payment.amount_rial,
        "currency": payment.currency,
        "status": payment.status,
        "reservation_reference": reservation.opaque_reference if reservation else None,
        "capture_journal_reference": payment.capture_journal_id,
        "refund_journal_reference": payment.refund_journal_id,
        "created_at": payment.created_at.isoformat(),
        "completed_at": payment.completed_at.isoformat() if payment.completed_at else None,
        "refunded_at": payment.completed_at.isoformat()
        if payment.status == "REFUNDED" and payment.completed_at
        else None,
        "failure_code": None,
        "idempotency_outcome": "not_exposed",
    }


@admin_wallet_reservation_router.get("/{reservation_reference}")
def admin_wallet_reservation_detail(
    reservation_reference: str,
    _: Annotated[object, Depends(require_perm("wallets.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    reservation = db.scalar(
        select(WalletReservationModel).where(
            WalletReservationModel.opaque_reference == reservation_reference
        )
    )
    if not reservation:
        reservation = db.get(WalletReservationModel, reservation_reference)
    if not reservation:
        raise _err(404, request, "RESERVATION_NOT_ACTIVE")
    order = db.scalar(
        select(OrderModel).where(OrderModel.reference == reservation.opaque_reference)
    )
    checkout = db.scalar(
        select(CheckoutSessionModel).where(
            CheckoutSessionModel.wallet_reservation_id == reservation.id
        )
    )
    return {
        "reservation_reference": reservation.opaque_reference,
        "order_reference": order.reference if order else None,
        "checkout_reference": checkout.reference if checkout else None,
        "customer": {"customer_id": reservation.customer_id},
        "amount_rial": reservation.amount_rial,
        "currency": reservation.currency,
        "status": reservation.status,
        "purpose_code": reservation.purpose_code,
        "created_at": reservation.created_at.isoformat(),
        "expires_at": reservation.expires_at.isoformat(),
        "released_at": reservation.released_at.isoformat() if reservation.released_at else None,
        "captured_at": reservation.captured_at.isoformat() if reservation.captured_at else None,
        "reserved_balance_contribution_rial": reservation.amount_rial
        if reservation.status == "ACTIVE"
        else 0,
    }


@admin_outbox_router.get("")
def admin_outbox(
    _: Annotated[object, Depends(require_perm("orders.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    stmt = (
        select(TransactionalOutboxModel)
        .order_by(TransactionalOutboxModel.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    if status:
        stmt = stmt.where(TransactionalOutboxModel.status == status)
    return {"items": [_outbox_view(db, r) for r in db.scalars(stmt).all()], "next_cursor": None}


def _outbox_view(db: Session, event: TransactionalOutboxModel) -> dict[str, Any]:
    payload = sanitize_metadata(event.payload or {})
    order = db.scalar(
        select(OrderModel).where(OrderModel.reference == payload.get("order_reference"))
    )
    return {
        "event_reference": event.id,
        "event_type": event.event_type,
        "event_version": payload.get("event_version"),
        "order_reference": payload.get("order_reference"),
        "product_version_id": payload.get("product_version_id"),
        "status": event.status,
        "attempt_count": event.attempt_count,
        "available_at": event.available_at.isoformat(),
        "claimed_at": event.claimed_at.isoformat() if event.claimed_at else None,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "last_failure_category": event.failure_category,
        "created_at": event.created_at.isoformat(),
        "correlation_id": payload.get("correlation_id"),
        "normalized_payload": {
            "order_reference": payload.get("order_reference"),
            "product_version_id": payload.get("product_version_id"),
            "selected_options": payload.get("selected_options"),
            "fulfillment_requirement_schema_version": payload.get(
                "fulfillment_requirement_schema_version"
            ),
        },
        "_order_exists": bool(order),
    }


@admin_outbox_router.get("/{event_reference}")
def admin_outbox_detail(
    event_reference: str,
    _: Annotated[object, Depends(require_perm("orders.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    event = db.get(TransactionalOutboxModel, event_reference)
    if not event:
        raise _err(404, request, "OUTBOX_EVENT_NOT_FOUND")
    return _outbox_view(db, event)
