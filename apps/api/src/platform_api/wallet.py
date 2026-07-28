from __future__ import annotations

import base64
import hmac
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.identity import UserStatus, sanitize_metadata
from vpnsale_domain.wallet import MAX_RIAL_AMOUNT, RialAmount, WalletBalanceBucket

from platform_api.config import Settings, get_settings
from platform_api.customer_auth.service import CustomerAccessTokenService
from platform_api.database import get_db_session
from platform_api.identity.models import AuditLogModel, CustomerSessionModel, UserModel
from platform_api.management import require_perm
from platform_api.wallet_models import (
    JournalEntryModel,
    LedgerAccountModel,
    LedgerPostingModel,
    WalletBalanceBucketModel,
    WalletBalanceProjectionModel,
    WalletCreditLotModel,
    WalletFinancialIdempotencyModel,
    WalletModel,
    WalletPolicyModel,
    WalletReconciliationRunModel,
    WalletReservationModel,
)

customer_router = APIRouter(prefix="/api/v1/customer/wallet", tags=["customer-wallet"])
admin_wallet_router = APIRouter(prefix="/api/v1/admin/management/wallets", tags=["admin-wallets"])
admin_ledger_router = APIRouter(prefix="/api/v1/admin/management/ledger", tags=["admin-ledger"])

SYSTEM_ACCOUNTS = {
    "ADMIN_ADJUSTMENT_EXPENSE": "ADMIN_ADJUSTMENT_EXPENSE",
    "ADMIN_ADJUSTMENT_RECOVERY": "ADMIN_ADJUSTMENT_RECOVERY",
    "ORDER_RESERVATION_CLEARING": "ORDER_RESERVATION_CLEARING",
    "PAYMENT_CLEARING": "PAYMENT_CLEARING",
    "PROMOTIONAL_EXPENSE": "PROMOTIONAL_EXPENSE",
    "REFUND_CLEARING": "REFUND_CLEARING",
}

CUSTOMER_BUCKET_LABELS = {
    "CASH": "موجودی نقدی",
    "REFUND": "بازپرداخت",
    "GIFT": "هدیه",
    "REFERRAL": "معرفی دوستان",
    "PROMOTIONAL": "اعتبار تبلیغاتی",
    "ADMIN_GRANT": "اعتبار مدیریتی",
}
CUSTOMER_CURSOR_VERSION = 1


class CustomerWalletBucket(BaseModel):
    bucket_type: str
    customer_label: str
    balance_rial: int
    expires_at: datetime | None = None


class CustomerWalletSummary(BaseModel):
    currency: Literal["IRR"]
    status: Literal["ACTIVE", "FROZEN", "CLOSED"]
    posted_balance_rial: int
    reserved_balance_rial: int
    available_balance_rial: int
    buckets: list[CustomerWalletBucket]
    updated_at: datetime
    has_expiring_credit: bool
    active_reservation_count: int


class WalletError(BaseModel):
    code: str
    message_key: str
    correlation_id: str


class AdjustmentRequest(BaseModel):
    customer_id: str
    amount_rial: int
    bucket_type: str = "ADMIN_GRANT"
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    reason: str = Field(min_length=1, max_length=240)
    internal_reference: str | None = Field(default=None, max_length=120)


class FreezeRequest(BaseModel):
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    reason: str = Field(min_length=1, max_length=240)


class PolicyUpdateRequest(BaseModel):
    minimum_topup_amount_rial: int = Field(ge=1, le=MAX_RIAL_AMOUNT)
    maximum_topup_amount_rial: int = Field(ge=1, le=MAX_RIAL_AMOUNT)
    maximum_wallet_balance_rial: int = Field(ge=1, le=MAX_RIAL_AMOUNT)
    default_reservation_lifetime_seconds: int = Field(ge=60, le=86400)
    maximum_reservation_lifetime_seconds: int = Field(ge=60, le=604800)
    promotional_credit_expiration_days: int = Field(ge=1, le=3660)
    referral_credit_expiration_days: int = Field(ge=1, le=3660)
    gift_credit_expiration_days: int = Field(ge=1, le=3660)
    spending_bucket_priority: list[str] = Field(min_length=1, max_length=6)
    customer_wallet_operations_enabled: bool
    max_transaction_history_page_size: int = Field(ge=1, le=100)
    reason: str = Field(min_length=1, max_length=240)


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _err(status: int, request: Request, code: str) -> HTTPException:
    return HTTPException(
        status,
        detail=WalletError(
            code=code, message_key=f"wallet.{code}", correlation_id=_cid(request)
        ).model_dump(),
    )


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _fingerprint(payload: str) -> str:
    return _hash(payload)


def _cursor_signature(payload: bytes, settings: Settings) -> str:
    return hmac.new(
        settings.customer_access_token_signing_key.encode(), payload, sha256
    ).hexdigest()


def _encode_customer_cursor(row: JournalEntryModel, wallet_id: str, settings: Settings) -> str:
    payload = json.dumps(
        {
            "v": CUSTOMER_CURSOR_VERSION,
            "wallet": wallet_id,
            "posted": row.posted_at.isoformat(),
            "id": row.id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    envelope = payload + b"." + _cursor_signature(payload, settings).encode()
    return base64.urlsafe_b64encode(envelope).decode().rstrip("=")


def _decode_customer_cursor(
    cursor: str, wallet_id: str, settings: Settings
) -> tuple[datetime, str]:
    if len(cursor) > 1024:
        raise ValueError("cursor too long")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        envelope = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload, supplied_signature = envelope.rsplit(b".", 1)
        expected = _cursor_signature(payload, settings).encode()
        data = json.loads(payload)
        posted_at = datetime.fromisoformat(data["posted"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("invalid cursor") from exc
    if not hmac.compare_digest(supplied_signature, expected):
        raise ValueError("invalid cursor signature")
    if data.get("v") != CUSTOMER_CURSOR_VERSION or data.get("wallet") != wallet_id:
        raise ValueError("cursor does not belong to wallet")
    entry_id = data.get("id")
    if posted_at.tzinfo is None or not isinstance(entry_id, str) or not entry_id:
        raise ValueError("invalid cursor values")
    return posted_at, entry_id


def _audit(
    db: Session,
    actor_type: str,
    actor_id: str | None,
    code: str,
    target_id: str | None,
    request: Request,
    metadata: dict[str, object],
) -> None:
    db.add(
        AuditLogModel(
            actor_type=actor_type,
            actor_id=actor_id,
            target_type="wallet",
            target_id=target_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            metadata_=sanitize_metadata(metadata),
        )
    )


def _policy(db: Session) -> WalletPolicyModel:
    policy = db.scalar(select(WalletPolicyModel).where(WalletPolicyModel.currency == "IRR"))
    if policy is None:
        policy = WalletPolicyModel(
            currency="IRR",
            minimum_topup_amount_rial=1_000_000,
            maximum_topup_amount_rial=500_000_000,
            maximum_wallet_balance_rial=2_000_000_000,
            default_reservation_lifetime_seconds=900,
            maximum_reservation_lifetime_seconds=3600,
            promotional_credit_expiration_days=30,
            referral_credit_expiration_days=90,
            gift_credit_expiration_days=180,
            spending_bucket_priority="CASH,REFUND,ADMIN_GRANT,GIFT,REFERRAL,PROMOTIONAL",
            customer_wallet_operations_enabled=True,
            max_transaction_history_page_size=50,
        )
        db.add(policy)
        db.flush()
    return policy


def _system_account(db: Session, code: str) -> LedgerAccountModel:
    acct = db.scalar(select(LedgerAccountModel).where(LedgerAccountModel.code == code))
    if acct is None:
        acct = LedgerAccountModel(
            code=code,
            account_type=SYSTEM_ACCOUNTS.get(code, code),
            currency="IRR",
            system_account=True,
        )
        db.add(acct)
        db.flush()
    return acct


def _wallet_account(db: Session, wallet: WalletModel, bucket: str) -> LedgerAccountModel:
    code = f"WALLET:{wallet.id}:{bucket}"
    acct = db.scalar(select(LedgerAccountModel).where(LedgerAccountModel.code == code))
    if acct is None:
        acct = LedgerAccountModel(
            code=code, account_type="CUSTOMER_WALLET_LIABILITY", currency="IRR", wallet_id=wallet.id
        )
        db.add(acct)
        db.flush()
    return acct


def _ensure_wallet(db: Session, customer_id: str) -> WalletModel:
    wallet = db.scalar(
        select(WalletModel).where(
            WalletModel.customer_id == customer_id, WalletModel.currency == "IRR"
        )
    )
    if wallet:
        return wallet
    wallet = WalletModel(customer_id=customer_id, currency="IRR", status="ACTIVE")
    db.add(wallet)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        wallet = db.scalar(
            select(WalletModel).where(
                WalletModel.customer_id == customer_id, WalletModel.currency == "IRR"
            )
        )
        if wallet is None:
            raise
        return wallet
    db.add(WalletBalanceProjectionModel(wallet_id=wallet.id))
    for b in WalletBalanceBucket:
        db.add(WalletBalanceBucketModel(wallet_id=wallet.id, bucket_type=b.value, balance_rial=0))
    db.flush()
    return wallet


def _projection(db: Session, wallet_id: str, lock: bool = False) -> WalletBalanceProjectionModel:
    stmt = select(WalletBalanceProjectionModel).where(
        WalletBalanceProjectionModel.wallet_id == wallet_id
    )
    if lock:
        stmt = stmt.with_for_update()
    proj = db.scalar(stmt)
    if proj is None:
        proj = WalletBalanceProjectionModel(wallet_id=wallet_id)
        db.add(proj)
        db.flush()
    return proj


def _bucket(db: Session, wallet_id: str, bucket_type: str) -> WalletBalanceBucketModel:
    row = db.scalar(
        select(WalletBalanceBucketModel)
        .where(
            WalletBalanceBucketModel.wallet_id == wallet_id,
            WalletBalanceBucketModel.bucket_type == bucket_type,
        )
        .with_for_update()
    )
    if row is None:
        row = WalletBalanceBucketModel(wallet_id=wallet_id, bucket_type=bucket_type, balance_rial=0)
        db.add(row)
        db.flush()
    return row


def _view(db: Session, wallet: WalletModel) -> dict[str, Any]:
    p = _projection(db, wallet.id)
    buckets = db.scalars(
        select(WalletBalanceBucketModel)
        .where(WalletBalanceBucketModel.wallet_id == wallet.id)
        .order_by(WalletBalanceBucketModel.bucket_type)
    ).all()
    if p.available_balance_rial + p.reserved_balance_rial != p.posted_balance_rial:
        raise ValueError("wallet balance projection invariant violated")
    now = datetime.now(UTC)
    expiring = db.scalar(
        select(func.count())
        .select_from(WalletCreditLotModel)
        .where(
            WalletCreditLotModel.wallet_id == wallet.id,
            WalletCreditLotModel.status == "ACTIVE",
            WalletCreditLotModel.remaining_amount_rial > 0,
            WalletCreditLotModel.expires_at.is_not(None),
            WalletCreditLotModel.expires_at > now,
        )
    )
    active_reservations = db.scalar(
        select(func.count())
        .select_from(WalletReservationModel)
        .where(
            WalletReservationModel.wallet_id == wallet.id,
            WalletReservationModel.status == "ACTIVE",
        )
    )
    return {
        "currency": wallet.currency,
        "status": wallet.status,
        "posted_balance_rial": p.posted_balance_rial,
        "reserved_balance_rial": p.reserved_balance_rial,
        "available_balance_rial": p.available_balance_rial,
        "buckets": [
            {
                "bucket_type": b.bucket_type,
                "customer_label": CUSTOMER_BUCKET_LABELS.get(b.bucket_type, "اعتبار دیگر"),
                "balance_rial": b.balance_rial,
                "expires_at": None,
            }
            for b in buckets
        ],
        "updated_at": p.updated_at,
        "has_expiring_credit": bool(expiring),
        "active_reservation_count": active_reservations or 0,
    }


def _post_adjustment(
    db: Session,
    wallet: WalletModel,
    op: str,
    amount: int,
    bucket_type: str,
    actor_id: str,
    request: Request,
    reason_code: str,
    idem: WalletFinancialIdempotencyModel | None = None,
    reversal_of_id: str | None = None,
) -> JournalEntryModel:
    RialAmount(amount)
    if wallet.status == "CLOSED":
        raise _err(409, request, "WALLET_CLOSED")
    p = _projection(db, wallet.id, lock=True)
    policy = _policy(db)
    if op == "ADMIN_CREDIT" and p.posted_balance_rial + amount > policy.maximum_wallet_balance_rial:
        raise _err(409, request, "MAXIMUM_BALANCE_EXCEEDED")
    if op == "ADMIN_DEBIT" and p.available_balance_rial < amount:
        raise _err(409, request, "INSUFFICIENT_AVAILABLE_BALANCE")
    wallet_acct = _wallet_account(db, wallet, bucket_type)
    system_acct = _system_account(
        db, "ADMIN_ADJUSTMENT_EXPENSE" if op == "ADMIN_CREDIT" else "ADMIN_ADJUSTMENT_RECOVERY"
    )
    now = datetime.now(UTC)
    je = JournalEntryModel(
        operation_code=op,
        status="POSTED",
        currency="IRR",
        wallet_id=wallet.id,
        actor_type="admin",
        actor_id=actor_id,
        correlation_id=_cid(request),
        idempotency_record_id=idem.id if idem else None,
        reversal_of_id=reversal_of_id,
        description_code=reason_code,
        safe_metadata={"reason_code": reason_code},
        occurred_at=now,
        posted_at=now,
    )
    db.add(je)
    db.flush()
    if op in {"ADMIN_CREDIT", "REVERSAL"}:
        postings = [(system_acct.id, "DEBIT"), (wallet_acct.id, "CREDIT")]
        delta = amount
    else:
        postings = [(wallet_acct.id, "DEBIT"), (system_acct.id, "CREDIT")]
        delta = -amount
    for idx, (acct, direction) in enumerate(postings, 1):
        db.add(
            LedgerPostingModel(
                journal_entry_id=je.id,
                ledger_account_id=acct,
                direction=direction,
                amount_rial=amount,
                posting_order=idx,
                purpose_code=op,
            )
        )
    p.posted_balance_rial += delta
    p.available_balance_rial = p.posted_balance_rial - p.reserved_balance_rial
    p.version += 1
    p.updated_at = now
    b = _bucket(db, wallet.id, bucket_type)
    b.balance_rial += delta
    if b.balance_rial < 0:
        raise _err(409, request, "INSUFFICIENT_AVAILABLE_BALANCE")
    if bucket_type in {"PROMOTIONAL", "REFERRAL", "GIFT"} and delta > 0:
        days = (
            policy.promotional_credit_expiration_days
            if bucket_type == "PROMOTIONAL"
            else policy.referral_credit_expiration_days
            if bucket_type == "REFERRAL"
            else policy.gift_credit_expiration_days
        )
        db.add(
            WalletCreditLotModel(
                wallet_id=wallet.id,
                bucket_type=bucket_type,
                original_amount_rial=amount,
                remaining_amount_rial=amount,
                issued_at=now,
                expires_at=now + timedelta(days=days),
                source_operation=op,
                journal_entry_id=je.id,
                status="ACTIVE",
            )
        )
    db.flush()
    return je


def ensure_customer_wallet(db: Session, customer_id: str) -> WalletModel:
    """Return the customer's IRR wallet, creating the standard projection rows if needed."""
    return _ensure_wallet(db, customer_id)


def build_wallet_admin_view(db: Session, wallet: WalletModel) -> dict[str, object]:
    """Build the public wallet summary shape used by admin/customer APIs."""
    return _view(db, wallet)


def post_admin_wallet_adjustment(
    db: Session,
    wallet: WalletModel,
    operation_code: Literal["ADMIN_CREDIT", "ADMIN_DEBIT", "REVERSAL"],
    amount_rial: int,
    bucket_type: str,
    actor_id: str,
    request: Request,
    reason_code: str,
    idem: WalletFinancialIdempotencyModel | None = None,
    reversal_of_id: str | None = None,
) -> JournalEntryModel:
    """Post a balanced administrative wallet adjustment journal."""
    return _post_adjustment(
        db,
        wallet,
        operation_code,
        amount_rial,
        bucket_type,
        actor_id,
        request,
        reason_code,
        idem,
        reversal_of_id,
    )


def current_wallet_customer_id(
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
    if not sess or sess.revoked_at or sess.consumed_at:
        raise _err(401, request, "UNAUTHENTICATED")
    user = db.get(UserModel, sess.user_id)
    if not user or user.status not in {
        UserStatus.ACTIVE.value,
        UserStatus.SUSPENDED.value,
        UserStatus.BLOCKED.value,
    }:
        raise _err(403, request, "PERMISSION_DENIED")
    return sess.user_id


def _customer_transaction_view(db: Session, row: JournalEntryModel) -> dict[str, Any]:
    posting = db.scalar(
        select(LedgerPostingModel)
        .join(LedgerAccountModel, LedgerPostingModel.ledger_account_id == LedgerAccountModel.id)
        .where(
            LedgerPostingModel.journal_entry_id == row.id,
            LedgerAccountModel.wallet_id == row.wallet_id,
        )
        .order_by(LedgerPostingModel.posting_order)
    )
    amount = posting.amount_rial if posting else None
    direction = (
        "INCOMING"
        if posting and posting.direction == "CREDIT"
        else "OUTGOING"
        if posting and posting.direction == "DEBIT"
        else "NEUTRAL"
    )
    return {
        "transaction_reference": row.id,
        "type": row.operation_code,
        "direction": direction,
        "amount_rial": amount,
        "currency": row.currency,
        "occurred_at": row.occurred_at.isoformat(),
        "posted_at": row.posted_at.isoformat(),
        "status": row.status,
        "safe_description_code": row.description_code,
        "reversal_of_reference": row.reversal_of_id,
    }


@customer_router.get("", response_model=CustomerWalletSummary)
def customer_wallet(
    customer_id: Annotated[str, Depends(current_wallet_customer_id)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    wallet = _ensure_wallet(db, customer_id)
    _audit(db, "customer", customer_id, "wallet.viewed", None, request, {})
    try:
        return _view(db, wallet)
    except ValueError as exc:
        raise _err(503, request, "PROJECTION_MISMATCH") from exc


@customer_router.get("/policy")
def customer_policy(
    _: Annotated[str, Depends(current_wallet_customer_id)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    p = _policy(db)
    return {
        "currency": p.currency,
        "minimum_topup_amount_rial": p.minimum_topup_amount_rial,
        "maximum_topup_amount_rial": p.maximum_topup_amount_rial,
        "maximum_wallet_balance_rial": p.maximum_wallet_balance_rial,
        "default_reservation_lifetime_seconds": p.default_reservation_lifetime_seconds,
        "maximum_reservation_lifetime_seconds": p.maximum_reservation_lifetime_seconds,
        "promotional_credit_expiration_days": p.promotional_credit_expiration_days,
        "referral_credit_expiration_days": p.referral_credit_expiration_days,
        "gift_credit_expiration_days": p.gift_credit_expiration_days,
        "customer_wallet_operations_enabled": p.customer_wallet_operations_enabled,
        "max_transaction_history_page_size": p.max_transaction_history_page_size,
    }


@customer_router.get("/transactions")
def customer_transactions(
    customer_id: Annotated[str, Depends(current_wallet_customer_id)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    wallet = _ensure_wallet(db, customer_id)
    policy = _policy(db)
    page_size = min(max(limit, 1), policy.max_transaction_history_page_size)
    boundary: tuple[datetime, str] | None = None
    if cursor:
        try:
            boundary = _decode_customer_cursor(cursor, wallet.id, settings)
        except ValueError as exc:
            raise _err(400, request, "INVALID_CURSOR") from exc
    statement = select(JournalEntryModel).where(JournalEntryModel.wallet_id == wallet.id)
    if boundary:
        posted_at, entry_id = boundary
        statement = statement.where(
            or_(
                JournalEntryModel.posted_at < posted_at,
                and_(JournalEntryModel.posted_at == posted_at, JournalEntryModel.id < entry_id),
            )
        )
    rows = db.scalars(
        statement.order_by(JournalEntryModel.posted_at.desc(), JournalEntryModel.id.desc()).limit(
            page_size + 1
        )
    ).all()
    has_more = len(rows) > page_size
    items = rows[:page_size]
    return {
        "items": [_customer_transaction_view(db, r) for r in items],
        "next_cursor": _encode_customer_cursor(items[-1], wallet.id, settings)
        if has_more and items
        else None,
    }


@customer_router.get("/transactions/{transaction_reference}")
def customer_transaction(
    transaction_reference: str,
    customer_id: Annotated[str, Depends(current_wallet_customer_id)],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    wallet = _ensure_wallet(db, customer_id)
    row = db.get(JournalEntryModel, transaction_reference)
    if not row or row.wallet_id != wallet.id:
        raise _err(404, request, "WALLET_NOT_FOUND")
    return _customer_transaction_view(db, row)


@customer_router.get("/credits")
def customer_credits(
    customer_id: Annotated[str, Depends(current_wallet_customer_id)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    wallet = _ensure_wallet(db, customer_id)
    rows = db.scalars(
        select(WalletCreditLotModel)
        .where(WalletCreditLotModel.wallet_id == wallet.id)
        .order_by(WalletCreditLotModel.expires_at)
    ).all()
    return {
        "items": [
            {
                "credit_reference": r.id,
                "bucket_type": r.bucket_type,
                "original_amount_rial": r.original_amount_rial,
                "remaining_amount_rial": r.remaining_amount_rial,
                "issued_at": r.issued_at.isoformat(),
                "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                "status": r.status,
                "source_operation": r.source_operation,
            }
            for r in rows
        ]
    }


@customer_router.get("/reservations")
def customer_reservations(
    customer_id: Annotated[str, Depends(current_wallet_customer_id)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    wallet = _ensure_wallet(db, customer_id)
    rows = db.scalars(
        select(WalletReservationModel)
        .where(WalletReservationModel.wallet_id == wallet.id)
        .order_by(WalletReservationModel.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "reservation_reference": r.id,
                "amount_rial": r.amount_rial,
                "currency": r.currency,
                "status": r.status,
                "purpose_code": r.purpose_code,
                "created_at": r.created_at.isoformat(),
                "expires_at": r.expires_at.isoformat(),
                "released_at": r.released_at.isoformat() if r.released_at else None,
                "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                "related_reference": r.opaque_reference,
            }
            for r in rows
        ]
    }


@admin_wallet_router.get("")
def admin_list_wallets(
    _: Annotated[object, Depends(require_perm("wallets.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> dict[str, Any]:
    rows = db.scalars(
        select(WalletModel).order_by(WalletModel.created_at.desc()).limit(min(max(limit, 1), 100))
    ).all()
    return {"items": [_view(db, w) for w in rows], "next_cursor": None}


@admin_wallet_router.get("/{wallet_id}")
def admin_wallet_detail(
    wallet_id: str,
    _: Annotated[object, Depends(require_perm("wallets.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    wallet = db.get(WalletModel, wallet_id)
    if not wallet:
        raise _err(404, request, "WALLET_NOT_FOUND")
    return _view(db, wallet)


@admin_wallet_router.post("/adjustments/credit")
def admin_credit(
    body: AdjustmentRequest,
    admin: Annotated[Any, Depends(require_perm("wallets.adjust"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str]:
    return _admin_adjust(body, "ADMIN_CREDIT", admin.id, db, request, idempotency_key)


@admin_wallet_router.post("/adjustments/debit")
def admin_debit(
    body: AdjustmentRequest,
    admin: Annotated[Any, Depends(require_perm("wallets.adjust"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str]:
    return _admin_adjust(body, "ADMIN_DEBIT", admin.id, db, request, idempotency_key)


def _admin_adjust(
    body: AdjustmentRequest,
    op: str,
    admin_id: str,
    db: Session,
    request: Request,
    idempotency_key: str | None,
) -> dict[str, str]:
    RialAmount(body.amount_rial)
    fp = _fingerprint(
        f"{op}|{body.customer_id}|{body.amount_rial}|{body.bucket_type}|{body.reason_code}|{body.reason}|{body.internal_reference}"
    )
    idem = None
    if idempotency_key:
        idem = db.scalar(
            select(WalletFinancialIdempotencyModel)
            .where(
                WalletFinancialIdempotencyModel.scope_type == "admin",
                WalletFinancialIdempotencyModel.scope_id == admin_id,
                WalletFinancialIdempotencyModel.operation_type == op,
                WalletFinancialIdempotencyModel.key_hash == _hash(idempotency_key),
            )
            .with_for_update()
        )
        if idem and idem.request_fingerprint != fp:
            raise _err(409, request, "IDEMPOTENCY_CONFLICT")
        if idem and idem.result_id:
            return {"journal_entry_reference": idem.result_id}
        if not idem:
            idem = WalletFinancialIdempotencyModel(
                scope_type="admin",
                scope_id=admin_id,
                operation_type=op,
                key_hash=_hash(idempotency_key),
                request_fingerprint=fp,
            )
            db.add(idem)
            db.flush()
    wallet = _ensure_wallet(db, body.customer_id)
    je = _post_adjustment(
        db,
        wallet,
        op,
        body.amount_rial,
        body.bucket_type,
        admin_id,
        request,
        body.reason_code,
        idem,
    )
    if idem:
        idem.result_type = "journal_entry"
        idem.result_id = je.id
    _audit(
        db,
        "admin",
        admin_id,
        f"wallet.{op.lower()}",
        wallet.id,
        request,
        {
            "wallet_id": wallet.id,
            "journal_id": je.id,
            "operation_code": op,
            "amount_rial": body.amount_rial,
            "currency": "IRR",
            "target_customer_id": body.customer_id,
            "reason_code": body.reason_code,
        },
    )
    return {"journal_entry_reference": je.id}


@admin_wallet_router.post("/{wallet_id}/freeze")
def freeze(
    wallet_id: str,
    body: FreezeRequest,
    admin: Annotated[Any, Depends(require_perm("wallets.freeze"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, str]:
    wallet = db.get(WalletModel, wallet_id)
    if not wallet:
        raise _err(404, request, "WALLET_NOT_FOUND")
    wallet.status = "FROZEN"
    wallet.updated_at = datetime.now(UTC)
    _audit(
        db,
        "admin",
        admin.id,
        "wallet.frozen",
        wallet.id,
        request,
        {"wallet_id": wallet.id, "reason_code": body.reason_code},
    )
    return {"wallet_reference": wallet.id, "status": wallet.status}


@admin_wallet_router.post("/{wallet_id}/unfreeze")
def unfreeze(
    wallet_id: str,
    body: FreezeRequest,
    admin: Annotated[Any, Depends(require_perm("wallets.freeze"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, str]:
    wallet = db.get(WalletModel, wallet_id)
    if not wallet:
        raise _err(404, request, "WALLET_NOT_FOUND")
    wallet.status = "ACTIVE"
    wallet.updated_at = datetime.now(UTC)
    _audit(
        db,
        "admin",
        admin.id,
        "wallet.unfrozen",
        wallet.id,
        request,
        {"wallet_id": wallet.id, "reason_code": body.reason_code},
    )
    return {"wallet_reference": wallet.id, "status": wallet.status}


@admin_wallet_router.post("/adjustments/{journal_id}/reverse")
def reverse(
    journal_id: str,
    admin: Annotated[Any, Depends(require_perm("wallets.adjust"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, str]:
    original = db.get(JournalEntryModel, journal_id)
    if (
        not original
        or not original.wallet_id
        or original.operation_code not in {"ADMIN_CREDIT", "ADMIN_DEBIT"}
    ):
        raise _err(409, request, "REVERSAL_NOT_ALLOWED")
    existing = db.scalar(
        select(JournalEntryModel).where(JournalEntryModel.reversal_of_id == journal_id)
    )
    if existing:
        return {"journal_entry_reference": existing.id}
    amount = (
        db.scalar(
            select(func.sum(LedgerPostingModel.amount_rial)).where(
                LedgerPostingModel.journal_entry_id == journal_id,
                LedgerPostingModel.direction == "CREDIT",
            )
        )
        or 0
    )
    wallet = db.get(WalletModel, original.wallet_id)
    if not wallet:
        raise _err(404, request, "WALLET_NOT_FOUND")
    op = "ADMIN_DEBIT" if original.operation_code == "ADMIN_CREDIT" else "ADMIN_CREDIT"
    je = _post_adjustment(
        db, wallet, op, int(amount), "ADMIN_GRANT", admin.id, request, "REVERSAL", None, journal_id
    )
    _audit(
        db,
        "admin",
        admin.id,
        "wallet.adjustment_reversed",
        wallet.id,
        request,
        {
            "wallet_id": wallet.id,
            "journal_id": je.id,
            "reversal_of": journal_id,
            "operation_code": "REVERSAL",
            "currency": "IRR",
        },
    )
    return {"journal_entry_reference": je.id}


@admin_wallet_router.get("/{wallet_id}/transactions")
def admin_wallet_transactions(
    wallet_id: str,
    _: Annotated[object, Depends(require_perm("wallets.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    rows = db.scalars(
        select(JournalEntryModel)
        .where(JournalEntryModel.wallet_id == wallet_id)
        .order_by(JournalEntryModel.posted_at.desc())
        .limit(100)
    ).all()
    return {
        "items": [
            {
                "journal_entry_reference": r.id,
                "operation_code": r.operation_code,
                "status": r.status,
                "posted_at": r.posted_at.isoformat(),
            }
            for r in rows
        ]
    }


@admin_ledger_router.get("/journals/{journal_id}")
def ledger_detail(
    journal_id: str,
    _: Annotated[object, Depends(require_perm("ledger.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    je = db.get(JournalEntryModel, journal_id)
    if not je:
        raise _err(404, request, "WALLET_NOT_FOUND")
    posts = db.execute(
        select(LedgerPostingModel, LedgerAccountModel)
        .join(LedgerAccountModel, LedgerPostingModel.ledger_account_id == LedgerAccountModel.id)
        .where(LedgerPostingModel.journal_entry_id == journal_id)
        .order_by(LedgerPostingModel.posting_order)
    ).all()
    return {
        "journal_entry_reference": je.id,
        "operation_code": je.operation_code,
        "currency": je.currency,
        "status": je.status,
        "postings": [
            {
                "direction": p.direction,
                "amount_rial": p.amount_rial,
                "account_code": a.code,
                "purpose_code": p.purpose_code,
            }
            for p, a in posts
        ],
    }


def _recalc(db: Session, wallet_id: str) -> dict[str, int]:
    rows = db.execute(
        select(
            LedgerPostingModel.direction,
            LedgerPostingModel.amount_rial,
            LedgerAccountModel.wallet_id,
        )
        .join(LedgerAccountModel, LedgerPostingModel.ledger_account_id == LedgerAccountModel.id)
        .where(LedgerAccountModel.wallet_id == wallet_id)
    ).all()
    posted = sum(int(a) if d == "CREDIT" else -int(a) for d, a, _ in rows)
    reserved = (
        db.scalar(
            select(func.coalesce(func.sum(WalletReservationModel.amount_rial), 0)).where(
                WalletReservationModel.wallet_id == wallet_id,
                WalletReservationModel.status == "ACTIVE",
            )
        )
        or 0
    )
    return {
        "posted_balance_rial": posted,
        "reserved_balance_rial": int(reserved),
        "available_balance_rial": posted - int(reserved),
    }


@admin_wallet_router.post("/{wallet_id}/reconcile")
def reconcile(
    wallet_id: str,
    admin: Annotated[Any, Depends(require_perm("ledger.reconcile"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
    repair: bool = False,
) -> dict[str, Any]:
    p = _projection(db, wallet_id, lock=repair)
    calc = _recalc(db, wallet_id)
    mismatches = {
        k: {"stored": getattr(p, k), "calculated": v} for k, v in calc.items() if getattr(p, k) != v
    }
    if repair and mismatches:
        p.posted_balance_rial = calc["posted_balance_rial"]
        p.reserved_balance_rial = calc["reserved_balance_rial"]
        p.available_balance_rial = calc["available_balance_rial"]
        p.version += 1
    run = WalletReconciliationRunModel(
        wallet_id=wallet_id,
        status="MISMATCH" if mismatches else "MATCH",
        mismatches=mismatches,
        repaired=repair and bool(mismatches),
        occurred_at=datetime.now(UTC),
        actor_id=admin.id,
    )
    db.add(run)
    _audit(
        db,
        "admin",
        admin.id,
        "wallet.reconciliation_run",
        wallet_id,
        request,
        {"wallet_id": wallet_id, "mismatch_count": len(mismatches), "repaired": repair},
    )
    return {
        "reconciliation_reference": run.id,
        "status": run.status,
        "mismatches": mismatches,
        "repaired": run.repaired,
    }


@admin_wallet_router.get("/policy/current")
def get_policy(
    _: Annotated[object, Depends(require_perm("wallets.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    p = _policy(db)
    return {
        "currency": p.currency,
        "minimum_topup_amount_rial": p.minimum_topup_amount_rial,
        "maximum_topup_amount_rial": p.maximum_topup_amount_rial,
        "maximum_wallet_balance_rial": p.maximum_wallet_balance_rial,
        "default_reservation_lifetime_seconds": p.default_reservation_lifetime_seconds,
        "maximum_reservation_lifetime_seconds": p.maximum_reservation_lifetime_seconds,
        "spending_bucket_priority": p.spending_bucket_priority.split(","),
        "promotional_credit_expiration_days": p.promotional_credit_expiration_days,
        "referral_credit_expiration_days": p.referral_credit_expiration_days,
        "gift_credit_expiration_days": p.gift_credit_expiration_days,
        "customer_wallet_operations_enabled": p.customer_wallet_operations_enabled,
        "max_transaction_history_page_size": p.max_transaction_history_page_size,
        "version": p.version,
    }


@admin_wallet_router.put("/policy/current")
def update_policy(
    body: PolicyUpdateRequest,
    admin: Annotated[Any, Depends(require_perm("wallets.policy.manage"))],
    db: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> dict[str, Any]:
    if (
        body.minimum_topup_amount_rial > body.maximum_topup_amount_rial
        or body.default_reservation_lifetime_seconds > body.maximum_reservation_lifetime_seconds
    ):
        raise _err(422, request, "INVALID_AMOUNT")
    p = _policy(db)
    for k, v in body.model_dump(exclude={"reason"}).items():
        setattr(p, k, ",".join(v) if k == "spending_bucket_priority" else v)
    p.version += 1
    p.updated_at = datetime.now(UTC)
    _audit(db, "admin", admin.id, "wallet.policy_updated", p.id, request, {"currency": "IRR"})
    return get_policy(admin, db)
