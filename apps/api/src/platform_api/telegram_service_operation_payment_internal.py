# pyright: reportPrivateUsage=false
"""Direct, idempotent wallet payment for Telegram service operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import or_, select
from vpnsale_domain.service_operation_payments import direct_wallet_payment_target_status
from vpnsale_domain.service_operations import (
    ServiceOperationDomainError,
    ServiceOperationStatus,
    ServiceOperationType,
)
from vpnsale_domain.wallet import RialAmount, WalletBalanceBucket

from .order_models import TransactionalOutboxModel
from .service_models import ServiceModel, ServiceOperationModel
from .service_operation_payment_models import ServiceOperationPaymentModel
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store
from .wallet import (
    _bucket,
    _ensure_wallet,
    _projection,
    _system_account,
    _wallet_account,
    wallet_policy,
)
from .wallet_models import (
    JournalEntryModel,
    LedgerPostingModel,
    WalletCreditLotModel,
    WalletReservationModel,
)

router = APIRouter(
    prefix="/api/v1/internal/telegram/service-management/operations",
    tags=["internal-telegram-service-operation-payment"],
    include_in_schema=False,
)

_LOT_BACKED_BUCKETS = frozenset({"PROMOTIONAL", "REFERRAL", "GIFT"})
_ELIGIBLE_LIFECYCLES = frozenset({"ACTIVE", "EXPIRED", "SUSPENDED", "DEGRADED"})
_POST_PAYMENT_STATUSES = frozenset(
    {ServiceOperationStatus.QUEUED.value, ServiceOperationStatus.PENDING_APPROVAL.value}
)


@dataclass(frozen=True)
class _BucketSpend:
    bucket_type: str
    amount_rial: int
    lots: tuple[WalletCreditLotModel, ...] = ()


def _payment_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def _quote_fields(operation: ServiceOperationModel) -> tuple[int, datetime, int, str]:
    quote = operation.quote_snapshot
    if not isinstance(quote, dict):
        raise _payment_error(status.HTTP_409_CONFLICT, "quote_snapshot_invalid")
    price = quote.get("price_rial")
    currency = quote.get("currency")
    expires_raw = quote.get("expires_at")
    service_version = quote.get("service_version")
    quote_id = quote.get("quote_id")
    if (
        type(price) is not int
        or price <= 0
        or currency != "IRR"
        or not isinstance(expires_raw, str)
        or type(service_version) is not int
        or service_version <= 0
        or not isinstance(quote_id, str)
        or not quote_id
    ):
        raise _payment_error(status.HTTP_409_CONFLICT, "quote_snapshot_invalid")
    try:
        expires_at = datetime.fromisoformat(expires_raw)
    except ValueError as exc:
        raise _payment_error(status.HTTP_409_CONFLICT, "quote_snapshot_invalid") from exc
    if expires_at.tzinfo is None:
        raise _payment_error(status.HTTP_409_CONFLICT, "quote_snapshot_invalid")
    return price, expires_at, service_version, quote_id


def _high_risk_operations(operation: ServiceOperationModel) -> frozenset[ServiceOperationType]:
    raw = operation.policy_snapshot.get("high_risk_operations")
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise _payment_error(status.HTTP_409_CONFLICT, "policy_snapshot_invalid")
    result: set[ServiceOperationType] = set()
    for value in raw:
        if not isinstance(value, str):
            raise _payment_error(status.HTTP_409_CONFLICT, "policy_snapshot_invalid")
        try:
            result.add(ServiceOperationType(value))
        except ValueError as exc:
            raise _payment_error(status.HTTP_409_CONFLICT, "policy_snapshot_invalid") from exc
    return frozenset(result)


def _locked_spend_plan(
    db: Database, wallet_id: str, amount_rial: int, now: datetime
) -> tuple[_BucketSpend, ...]:
    policy = wallet_policy(db)
    if not policy.customer_wallet_operations_enabled:
        raise _payment_error(status.HTTP_409_CONFLICT, "wallet_operations_disabled")
    priority = [item.strip() for item in policy.spending_bucket_priority.split(",") if item.strip()]
    if not priority or len(priority) != len(set(priority)):
        raise _payment_error(status.HTTP_409_CONFLICT, "wallet_policy_invalid")

    remaining = amount_rial
    plan: list[_BucketSpend] = []
    for bucket_name in priority:
        try:
            WalletBalanceBucket(bucket_name)
        except ValueError as exc:
            raise _payment_error(status.HTTP_409_CONFLICT, "wallet_policy_invalid") from exc
        bucket = _bucket(db, wallet_id, bucket_name)
        lots: tuple[WalletCreditLotModel, ...] = ()
        spendable = bucket.balance_rial
        if bucket_name in _LOT_BACKED_BUCKETS:
            lots = tuple(
                db.scalars(
                    select(WalletCreditLotModel)
                    .where(
                        WalletCreditLotModel.wallet_id == wallet_id,
                        WalletCreditLotModel.bucket_type == bucket_name,
                        WalletCreditLotModel.status == "ACTIVE",
                        WalletCreditLotModel.remaining_amount_rial > 0,
                        or_(
                            WalletCreditLotModel.expires_at.is_(None),
                            WalletCreditLotModel.expires_at > now,
                        ),
                    )
                    .order_by(
                        WalletCreditLotModel.expires_at.asc(),
                        WalletCreditLotModel.issued_at.asc(),
                        WalletCreditLotModel.id.asc(),
                    )
                    .with_for_update()
                )
            )
            spendable = min(spendable, sum(lot.remaining_amount_rial for lot in lots))
        take = min(spendable, remaining)
        if take > 0:
            plan.append(_BucketSpend(bucket_name, take, lots))
            remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise _payment_error(status.HTTP_402_PAYMENT_REQUIRED, "insufficient_wallet_balance")
    return tuple(plan)


def _consume_lot_backing(spend: _BucketSpend) -> None:
    remaining = spend.amount_rial
    for lot in spend.lots:
        take = min(lot.remaining_amount_rial, remaining)
        lot.remaining_amount_rial -= take
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise RuntimeError("wallet credit lot backing invariant violated")


def _payment_view(
    payment: ServiceOperationPaymentModel,
    operation: ServiceOperationModel,
    service: ServiceModel,
) -> dict[str, object]:
    post_payment_status = payment.spend_snapshot.get("post_payment_operation_status")
    if post_payment_status not in _POST_PAYMENT_STATUSES:
        raise _payment_error(status.HTTP_409_CONFLICT, "payment_snapshot_invalid")
    return {
        "payment_reference": payment.id,
        "operation_reference": operation.id,
        "service_reference": service.public_reference,
        "operation_type": operation.operation_type,
        "status": post_payment_status,
        "amount_rial": payment.amount_rial,
        "currency": payment.currency,
        "reservation_reference": payment.reservation_id,
        "capture_journal_reference": payment.capture_journal_id,
        "queued": post_payment_status == ServiceOperationStatus.QUEUED.value,
    }


@router.post("/{operation_reference}/pay")
def pay_service_operation(
    operation_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    operation = db.scalar(
        select(ServiceOperationModel)
        .where(
            ServiceOperationModel.id == operation_reference,
            ServiceOperationModel.requester_type == "CUSTOMER",
            ServiceOperationModel.requester_id == customer_id,
        )
        .with_for_update()
    )
    if operation is None:
        raise _payment_error(status.HTTP_404_NOT_FOUND, "service_operation_not_found")
    service = db.get(ServiceModel, operation.service_id)
    if service is None or service.beneficiary_customer_id != customer_id:
        raise _payment_error(status.HTTP_404_NOT_FOUND, "service_operation_not_found")

    existing = db.scalar(
        select(ServiceOperationPaymentModel).where(
            ServiceOperationPaymentModel.operation_id == operation.id
        )
    )
    if existing is not None:
        _no_store(response)
        return _payment_view(existing, operation, service)

    if service.lifecycle not in _ELIGIBLE_LIFECYCLES:
        raise _payment_error(status.HTTP_409_CONFLICT, "service_not_eligible")
    price_rial, quote_expires_at, quoted_service_version, quote_id = _quote_fields(operation)
    if service.version != quoted_service_version:
        raise _payment_error(status.HTTP_409_CONFLICT, "service_changed_since_quote")
    try:
        operation_type = ServiceOperationType(operation.operation_type)
        target_status = direct_wallet_payment_target_status(
            current_status=ServiceOperationStatus(operation.status),
            operation_type=operation_type,
            high_risk_operations=_high_risk_operations(operation),
            quote_expires_at=quote_expires_at,
            now=datetime.now(UTC),
        )
        RialAmount(price_rial)
    except (ValueError, OverflowError, ServiceOperationDomainError) as exc:
        raise _payment_error(status.HTTP_409_CONFLICT, "service_operation_payment_invalid") from exc

    wallet = _ensure_wallet(db, customer_id)
    if wallet.status != "ACTIVE":
        raise _payment_error(status.HTTP_409_CONFLICT, "wallet_not_active")
    projection = _projection(db, wallet.id, lock=True)
    if projection.available_balance_rial < price_rial:
        raise _payment_error(status.HTTP_402_PAYMENT_REQUIRED, "insufficient_wallet_balance")

    now = datetime.now(UTC)
    spend_plan = _locked_spend_plan(db, wallet.id, price_rial, now)
    reservation = WalletReservationModel(
        wallet_id=wallet.id,
        customer_id=customer_id,
        amount_rial=price_rial,
        currency="IRR",
        status="ACTIVE",
        purpose_code="SERVICE_OPERATION",
        opaque_reference=operation.id,
        safe_metadata={"operation_id": operation.id, "quote_id": quote_id},
        created_at=now,
        expires_at=quote_expires_at,
    )
    db.add(reservation)
    db.flush()
    projection.reserved_balance_rial += price_rial
    projection.available_balance_rial = (
        projection.posted_balance_rial - projection.reserved_balance_rial
    )
    projection.version += 1

    journal = JournalEntryModel(
        operation_code="SERVICE_OPERATION_WALLET_CAPTURE",
        status="POSTED",
        currency="IRR",
        wallet_id=wallet.id,
        actor_type="customer",
        actor_id=customer_id,
        correlation_id=f"service-operation:{operation.id}",
        description_code="SERVICE_OPERATION_PAYMENT",
        safe_metadata={
            "operation_id": operation.id,
            "service_reference": service.public_reference,
            "operation_type": operation.operation_type,
        },
        occurred_at=now,
        posted_at=now,
    )
    db.add(journal)
    db.flush()

    for position, spend in enumerate(spend_plan, 1):
        account = _wallet_account(db, wallet, spend.bucket_type)
        db.add(
            LedgerPostingModel(
                journal_entry_id=journal.id,
                ledger_account_id=account.id,
                direction="DEBIT",
                amount_rial=spend.amount_rial,
                posting_order=position,
                purpose_code="SERVICE_OPERATION_WALLET_CAPTURE",
            )
        )
        bucket = _bucket(db, wallet.id, spend.bucket_type)
        bucket.balance_rial -= spend.amount_rial
        if spend.bucket_type in _LOT_BACKED_BUCKETS:
            _consume_lot_backing(spend)
    clearing = _system_account(db, "PAYMENT_CLEARING")
    db.add(
        LedgerPostingModel(
            journal_entry_id=journal.id,
            ledger_account_id=clearing.id,
            direction="CREDIT",
            amount_rial=price_rial,
            posting_order=len(spend_plan) + 1,
            purpose_code="SERVICE_OPERATION_WALLET_CAPTURE",
        )
    )

    projection.posted_balance_rial -= price_rial
    projection.reserved_balance_rial -= price_rial
    projection.available_balance_rial = (
        projection.posted_balance_rial - projection.reserved_balance_rial
    )
    projection.version += 1
    projection.updated_at = now
    reservation.status = "CAPTURED"
    reservation.captured_at = now

    fingerprint = hashlib.sha256(f"{operation.id}|{quote_id}|{price_rial}|IRR".encode()).hexdigest()
    payment = ServiceOperationPaymentModel(
        operation_id=operation.id,
        customer_id=customer_id,
        wallet_id=wallet.id,
        reservation_id=reservation.id,
        capture_journal_id=journal.id,
        amount_rial=price_rial,
        currency="IRR",
        status="CAPTURED",
        idempotency_key_hash=hashlib.sha256(idempotency_key.encode()).hexdigest(),
        request_fingerprint=fingerprint,
        spend_snapshot={
            "post_payment_operation_status": target_status.value,
            "buckets": [
                {"bucket_type": spend.bucket_type, "amount_rial": spend.amount_rial}
                for spend in spend_plan
            ],
        },
        created_at=now,
        completed_at=now,
    )
    db.add(payment)
    db.flush()

    operation.status = target_status.value
    operation.updated_at = now
    operation.version += 1
    if target_status is ServiceOperationStatus.QUEUED:
        db.add(
            TransactionalOutboxModel(
                event_key=f"service_operation.ready:{operation.id}",
                event_type="service_operation.ready.v1",
                status="PENDING",
                payload={
                    "event_version": 1,
                    "operation_id": operation.id,
                    "service_id": service.id,
                    "service_reference": service.public_reference,
                    "customer_id": customer_id,
                    "operation_type": operation.operation_type,
                    "payment_id": payment.id,
                    "correlation_id": f"service-operation:{operation.id}",
                    "occurred_at": now.isoformat(),
                },
                available_at=now,
            )
        )
    _no_store(response)
    return _payment_view(payment, operation, service)
