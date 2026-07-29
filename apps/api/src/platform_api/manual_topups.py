"""Authenticated manual card-transfer request and review APIs."""

from __future__ import annotations

import hashlib
import io
import json
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vpnsale_domain.identity import sanitize_metadata
from vpnsale_domain.manual_topups import (
    ManualTopupStatus,
    approval_amounts,
    customer_safe_text,
    require_transition,
    validate_requested_amount,
)

from platform_api.admin_auth.rate_limit import RateLimiter, RateLimitUnavailable
from platform_api.admin_auth.routes import get_rate_limiter
from platform_api.admin_auth.service import AccessTokenService
from platform_api.config import Settings, get_settings
from platform_api.customer_auth.routes import current_customer_session_dependency
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.database import get_db_session
from platform_api.identity.models import (
    AdminModel,
    AdminSessionModel,
    AuditLogModel,
    CustomerProfileModel,
    CustomerSessionModel,
    TelegramAccountModel,
)
from platform_api.management import active_permissions, require_perm
from platform_api.manual_topup_models import (
    ManualTopupDecisionModel,
    ManualTopupIdempotencyModel,
    ManualTopupMessageModel,
    ManualTopupNotificationOutboxModel,
    ManualTopupReceiptModel,
    ManualTopupRequestModel,
)
from platform_api.manual_topup_storage import InvalidReceipt, LocalPrivateReceiptStorage
from platform_api.wallet import post_wallet_adjustment, wallet_policy, wallet_projection
from platform_api.wallet_models import WalletModel

customer_router = APIRouter(
    prefix="/api/v1/customer/manual-topups", tags=["customer-manual-topups"]
)
admin_router = APIRouter(prefix="/api/v1/admin/manual-topups", tags=["admin-manual-topups"])
MAX_READ_PAGE = 100
NONTERMINAL = ("AWAITING_SUPPORT", "AWAITING_RECEIPT", "UNDER_REVIEW", "NEEDS_RESUBMISSION")


class CreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_rial: int = Field(ge=1_000_000)
    customer_note: str | None = Field(default=None, max_length=500)
    source_channel: Literal["WEB", "TELEGRAM_MINI_APP"] = "WEB"


class VersionedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0)
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    customer_message: str = Field(min_length=1, max_length=1000)
    internal_note: str | None = Field(default=None, max_length=1000)


class AdminMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=1000)


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0)
    verified_transfer_amount_rial: int = Field(gt=0)
    bonus_amount_rial: int = Field(default=0, ge=0)
    reason_code: str | None = Field(default=None, pattern=r"^[A-Z0-9_]{3,64}$")
    internal_note: str | None = Field(default=None, max_length=1000)
    customer_message: str | None = Field(default=None, max_length=1000)
    strong_confirmation_token: str = Field(min_length=32, max_length=256)
    override_acknowledged: bool = False


class StrongConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_reference: str = Field(min_length=8, max_length=48)
    current_password: str = Field(min_length=1, max_length=1024)
    totp_code: str = Field(min_length=6, max_length=64)
    override_acknowledged: bool = False


def _now() -> datetime:
    return datetime.now(UTC)


def _ref(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(20).replace('-', '').replace('_', '')[:26]}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _fingerprint(value: object) -> str:
    return _hash(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


def _error(status: int, code: str) -> HTTPException:
    return HTTPException(
        status, detail={"code": code, "message_key": f"manual_topup.{code.lower()}"}
    )


def _enabled(settings: Settings) -> None:
    if not settings.manual_card_topups_enabled:
        raise _error(503, "FEATURE_DISABLED")


async def _rate(limiter: RateLimiter, purpose: str, subject: str, limit: int) -> None:
    try:
        result = await limiter.check(purpose, subject, limit=limit, window_seconds=3600)
    except RateLimitUnavailable as exc:
        raise _error(503, "RATE_LIMIT_UNAVAILABLE") from exc
    if not result.allowed:
        raise HTTPException(
            429, detail={"code": "RATE_LIMITED"}, headers={"Retry-After": str(result.retry_after)}
        )


def _customer_csrf(
    db: Session, settings: Settings, session: CustomerSessionModel, token: str | None
) -> None:
    if not CustomerAuthService(db, settings).validate_csrf(session, token):
        raise _error(403, "CSRF_FAILED")


def _admin_session(db: Session, settings: Settings, authorization: str | None) -> AdminSessionModel:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _error(401, "UNAUTHENTICATED")
    try:
        claims = AccessTokenService(settings).validate(authorization.split(" ", 1)[1])
    except ValueError as exc:
        raise _error(401, "UNAUTHENTICATED") from exc
    session = db.get(AdminSessionModel, claims["session_id"])
    if session is None or session.revoked_at or session.consumed_at:
        raise _error(401, "UNAUTHENTICATED")
    return session


def _admin_csrf(session: AdminSessionModel, token: str | None) -> None:
    if (
        not token
        or not session.csrf_token_hash
        or not secrets.compare_digest(token, session.csrf_token_hash)
    ):
        raise _error(403, "CSRF_FAILED")


def _idem(
    db: Session,
    *,
    scope: str,
    scope_id: str,
    operation: str,
    key: str | None,
    fingerprint: str,
    result: str | None = None,
) -> str | None:
    if not key or len(key) > 200:
        raise _error(400, "IDEMPOTENCY_KEY_REQUIRED")
    key_hash = _hash(key)
    prior = db.scalar(
        select(ManualTopupIdempotencyModel).where(
            ManualTopupIdempotencyModel.scope == scope,
            ManualTopupIdempotencyModel.scope_id == scope_id,
            ManualTopupIdempotencyModel.operation == operation,
            ManualTopupIdempotencyModel.key_hash == key_hash,
        )
    )
    if prior:
        if prior.request_fingerprint != fingerprint:
            raise _error(409, "IDEMPOTENCY_CONFLICT")
        return prior.result_reference
    if result is not None:
        db.add(
            ManualTopupIdempotencyModel(
                scope=scope,
                scope_id=scope_id,
                operation=operation,
                key_hash=key_hash,
                request_fingerprint=fingerprint,
                result_reference=result,
                expires_at=_now() + timedelta(days=8),
            )
        )
    return None


def _request(
    db: Session, reference: str, customer_id: str | None = None, lock: bool = False
) -> ManualTopupRequestModel:
    stmt = select(ManualTopupRequestModel).where(ManualTopupRequestModel.reference == reference)
    if customer_id:
        stmt = stmt.where(ManualTopupRequestModel.customer_id == customer_id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise _error(404, "NOT_FOUND")
    return row


def _customer_dto(db: Session, row: ManualTopupRequestModel) -> dict[str, object]:
    receipt = (
        db.get(ManualTopupReceiptModel, row.current_receipt_id) if row.current_receipt_id else None
    )
    messages = db.scalars(
        select(ManualTopupMessageModel)
        .where(
            ManualTopupMessageModel.request_id == row.id,
            ManualTopupMessageModel.visibility == "CUSTOMER",
        )
        .order_by(ManualTopupMessageModel.created_at, ManualTopupMessageModel.reference)
    ).all()
    timeline: list[dict[str, object]] = [{"event": "CREATED", "at": row.created_at}]
    if row.submitted_at:
        timeline.append({"event": "RECEIPT_SUBMITTED", "at": row.submitted_at})
    if row.decided_at:
        timeline.append({"event": row.status, "at": row.decided_at})
    return {
        "reference": row.reference,
        "requested_amount_rial": row.requested_amount_rial,
        "currency": "IRR",
        "status": row.status,
        "source_channel": row.source_channel,
        "created_at": row.created_at,
        "submitted_at": row.submitted_at,
        "decided_at": row.decided_at,
        "receipt_state": receipt.security_state if receipt else "MISSING",
        "current_receipt_reference": receipt.reference if receipt else None,
        "customer_message": row.customer_message,
        "messages": [
            {"reference": m.reference, "body": m.body, "created_at": m.created_at} for m in messages
        ],
        "verified_amount_rial": row.verified_transfer_amount_rial,
        "bonus_amount_rial": row.bonus_amount_rial,
        "total_credited_rial": row.total_credited_amount_rial,
        "timeline": timeline,
        "version": row.version,
    }


def _outbox(db: Session, row: ManualTopupRequestModel, event: str, mutation_ref: str) -> None:
    db.add(
        ManualTopupNotificationOutboxModel(
            event_reference=_ref("mtn"),
            deduplication_key=f"{row.reference}:{event}:{mutation_ref}",
            request_id=row.id,
            event_type=event,
            customer_id=row.customer_id,
            delivery_channel="IN_APP",
            status="PENDING",
            attempts=0,
            available_at=_now(),
        )
    )


def _message(
    db: Session, row: ManualTopupRequestModel, admin_id: str, body: str
) -> ManualTopupMessageModel:
    safe = customer_safe_text(body)
    message = ManualTopupMessageModel(
        reference=_ref("mtm"),
        request_id=row.id,
        sender_type="ADMIN",
        sender_reference=admin_id,
        visibility="CUSTOMER",
        body=safe,
    )
    db.add(message)
    return message


def _audit(
    db: Session, admin_id: str, code: str, row: ManualTopupRequestModel, request: Request
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin_id,
            target_type="manual_topup",
            target_id=row.id,
            event_code=code,
            occurred_at=_now(),
            correlation_id=request.headers.get("x-request-id", "local"),
            metadata_=sanitize_metadata({"reference": row.reference, "version": row.version}),
        )
    )


@customer_router.post("")
async def create_manual_topup(
    body: CreateRequest,
    request: Request,
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    _enabled(settings)
    _customer_csrf(db, settings, session, csrf)
    await _rate(limiter, "manual-topup-create", session.user_id, 10)
    policy = wallet_policy(db)
    validate_requested_amount(body.amount_rial, policy.maximum_topup_amount_rial)
    wallet = db.scalar(
        select(WalletModel).where(
            WalletModel.customer_id == session.user_id, WalletModel.currency == "IRR"
        )
    )
    if wallet is None or wallet.status != "ACTIVE":
        raise _error(409, "ACTIVE_WALLET_REQUIRED")
    if (
        wallet_projection(db, wallet.id).posted_balance_rial + body.amount_rial
        > policy.maximum_wallet_balance_rial
    ):
        raise _error(409, "MAXIMUM_BALANCE_EXCEEDED")
    fp = _fingerprint(body.model_dump())
    prior = _idem(
        db,
        scope="CUSTOMER",
        scope_id=session.user_id,
        operation="CREATE",
        key=idempotency_key,
        fingerprint=fp,
    )
    if prior:
        return _customer_dto(db, _request(db, prior, session.user_id))
    active = (
        db.scalar(
            select(func.count())
            .select_from(ManualTopupRequestModel)
            .where(
                ManualTopupRequestModel.customer_id == session.user_id,
                ManualTopupRequestModel.status.in_(NONTERMINAL),
            )
        )
        or 0
    )
    if active >= settings.manual_topup_max_active_requests:
        raise _error(409, "ACTIVE_REQUEST_LIMIT")
    reference = _ref("mtp")
    row = ManualTopupRequestModel(
        reference=reference,
        customer_id=session.user_id,
        wallet_id=wallet.id,
        requested_amount_rial=body.amount_rial,
        currency="IRR",
        status="AWAITING_SUPPORT",
        source_channel=body.source_channel,
        customer_note=body.customer_note,
        expires_at=_now() + timedelta(days=7),
        version=1,
    )
    db.add(row)
    db.flush()
    _idem(
        db,
        scope="CUSTOMER",
        scope_id=session.user_id,
        operation="CREATE",
        key=idempotency_key,
        fingerprint=fp,
        result=reference,
    )
    return _customer_dto(db, row)


@customer_router.get("")
def list_manual_topups(
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=MAX_READ_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> dict[str, object]:
    rows = db.scalars(
        select(ManualTopupRequestModel)
        .where(ManualTopupRequestModel.customer_id == session.user_id)
        .order_by(ManualTopupRequestModel.created_at.desc(), ManualTopupRequestModel.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {"items": [_customer_dto(db, row) for row in rows], "limit": limit, "offset": offset}


@customer_router.get("/{reference}")
def detail_manual_topup(
    reference: str,
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    return _customer_dto(db, _request(db, reference, session.user_id))


@customer_router.post("/{reference}/receipts")
async def upload_receipt(
    reference: str,
    request: Request,
    image: Annotated[UploadFile, File()],
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    _enabled(settings)
    _customer_csrf(db, settings, session, csrf)
    await _rate(limiter, "manual-topup-receipt", session.user_id, 20)
    raw = await image.read(settings.manual_topup_max_receipt_bytes + 1)
    if len(raw) > settings.manual_topup_max_receipt_bytes:
        raise _error(413, "RECEIPT_TOO_LARGE")
    fp = _fingerprint(
        {"content_type": image.content_type, "sha256": hashlib.sha256(raw).hexdigest()}
    )
    prior = _idem(
        db,
        scope="REQUEST",
        scope_id=reference,
        operation="RECEIPT",
        key=idempotency_key,
        fingerprint=fp,
    )
    if prior:
        return _customer_dto(db, _request(db, reference, session.user_id))
    row = _request(db, reference, session.user_id, lock=True)
    try:
        require_transition(ManualTopupStatus(row.status), ManualTopupStatus.UNDER_REVIEW)
    except ValueError as exc:
        raise _error(409, "INVALID_TRANSITION") from exc
    count = (
        db.scalar(
            select(func.count())
            .select_from(ManualTopupReceiptModel)
            .where(ManualTopupReceiptModel.request_id == row.id)
        )
        or 0
    )
    if count >= settings.manual_topup_max_receipt_versions:
        raise _error(409, "RECEIPT_VERSION_LIMIT")
    storage = LocalPrivateReceiptStorage(
        Path(settings.manual_topup_private_upload_root),
        maximum_bytes=settings.manual_topup_max_receipt_bytes,
        dimension_limit=settings.manual_topup_image_dimension_limit,
    )
    try:
        stored = storage.store(io.BytesIO(raw), image.content_type or "")
    except InvalidReceipt as exc:
        raise _error(422, "INVALID_RECEIPT") from exc
    try:
        old = (
            db.get(ManualTopupReceiptModel, row.current_receipt_id)
            if row.current_receipt_id
            else None
        )
        if old:
            old.superseded_at = _now()
        receipt = ManualTopupReceiptModel(
            reference=_ref("mtr"),
            request_id=row.id,
            receipt_version=count + 1,
            storage_key=stored.storage_key,
            sanitized_sha256=stored.sanitized_sha256,
            byte_size=stored.byte_size,
            media_type=stored.media_type,
            width=stored.width,
            height=stored.height,
            source_channel=row.source_channel,
            security_state="SANITIZED",
        )
        db.add(receipt)
        db.flush()
        row.current_receipt_id = receipt.id
        row.status = "UNDER_REVIEW"
        row.submitted_at = _now()
        row.version += 1
        _outbox(db, row, "RECEIPT_SUBMITTED", receipt.reference)
        _idem(
            db,
            scope="REQUEST",
            scope_id=reference,
            operation="RECEIPT",
            key=idempotency_key,
            fingerprint=fp,
            result=receipt.reference,
        )
        db.flush()
    except Exception:
        storage.delete(stored.storage_key)
        raise
    return _customer_dto(db, row)


def _stream(db: Session, row: ManualTopupRequestModel, settings: Settings) -> StreamingResponse:
    receipt = (
        db.get(ManualTopupReceiptModel, row.current_receipt_id) if row.current_receipt_id else None
    )
    if receipt is None:
        raise _error(404, "RECEIPT_NOT_FOUND")
    storage = LocalPrivateReceiptStorage(Path(settings.manual_topup_private_upload_root))
    suffix = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[receipt.media_type]
    return StreamingResponse(
        storage.open(receipt.storage_key),
        media_type=receipt.media_type,
        headers={
            "Content-Disposition": f'inline; filename="receipt-{receipt.reference}.{suffix}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@customer_router.get("/{reference}/receipt")
def customer_receipt(
    reference: str,
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    return _stream(db, _request(db, reference, session.user_id), settings)


@customer_router.post("/{reference}/cancel")
async def cancel(
    reference: str,
    session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> dict[str, object]:
    _enabled(settings)
    _customer_csrf(db, settings, session, csrf)
    await _rate(limiter, "manual-topup-cancel", session.user_id, 10)
    fp = _fingerprint({"reference": reference})
    prior = _idem(
        db,
        scope="REQUEST",
        scope_id=reference,
        operation="CANCEL",
        key=idempotency_key,
        fingerprint=fp,
    )
    row = _request(db, reference, session.user_id, lock=not bool(prior))
    if prior:
        return _customer_dto(db, row)
    try:
        require_transition(ManualTopupStatus(row.status), ManualTopupStatus.CANCELLED)
    except ValueError as exc:
        raise _error(409, "INVALID_TRANSITION") from exc
    row.status = "CANCELLED"
    row.decided_at = _now()
    row.version += 1
    _idem(
        db,
        scope="REQUEST",
        scope_id=reference,
        operation="CANCEL",
        key=idempotency_key,
        fingerprint=fp,
        result=reference,
    )
    return _customer_dto(db, row)


def _admin_dto(db: Session, row: ManualTopupRequestModel) -> dict[str, object]:
    profile = db.get(CustomerProfileModel, row.customer_id)
    telegram = db.scalar(
        select(TelegramAccountModel).where(TelegramAccountModel.user_id == row.customer_id)
    )
    wallet = db.get(WalletModel, row.wallet_id)
    projection = wallet_projection(db, row.wallet_id)
    receipts = db.scalars(
        select(ManualTopupReceiptModel)
        .where(ManualTopupReceiptModel.request_id == row.id)
        .order_by(ManualTopupReceiptModel.receipt_version)
    ).all()
    decisions = db.scalars(
        select(ManualTopupDecisionModel)
        .where(ManualTopupDecisionModel.request_id == row.id)
        .order_by(ManualTopupDecisionModel.created_at)
    ).all()
    messages = db.scalars(
        select(ManualTopupMessageModel)
        .where(ManualTopupMessageModel.request_id == row.id)
        .order_by(ManualTopupMessageModel.created_at)
    ).all()
    events = db.scalars(
        select(ManualTopupNotificationOutboxModel)
        .where(ManualTopupNotificationOutboxModel.request_id == row.id)
        .order_by(ManualTopupNotificationOutboxModel.created_at)
    ).all()
    duplicate = False
    if receipts:
        duplicate = bool(
            db.scalar(
                select(func.count())
                .select_from(ManualTopupReceiptModel)
                .where(
                    ManualTopupReceiptModel.sanitized_sha256 == receipts[-1].sanitized_sha256,
                    ManualTopupReceiptModel.request_id != row.id,
                )
            )
        )
    return {
        "reference": row.reference,
        "status": row.status,
        "version": row.version,
        "customer": {
            "display_name": profile.display_name if profile else None,
            "telegram_username": telegram.username if telegram else None,
        },
        "wallet": {
            "status": wallet.status if wallet else "MISSING",
            "available_balance_rial": projection.available_balance_rial,
        },
        "requested_amount_rial": row.requested_amount_rial,
        "currency": "IRR",
        "source_channel": row.source_channel,
        "created_at": row.created_at,
        "submitted_at": row.submitted_at,
        "decided_at": row.decided_at,
        "receipt_state": receipts[-1].security_state if receipts else "MISSING",
        "current_receipt_reference": receipts[-1].reference if receipts else None,
        "duplicate_receipt_warning": duplicate,
        "receipts": [
            {
                "reference": r.reference,
                "version": r.receipt_version,
                "media_type": r.media_type,
                "byte_size": r.byte_size,
                "width": r.width,
                "height": r.height,
                "security_state": r.security_state,
                "created_at": r.created_at,
                "superseded_at": r.superseded_at,
            }
            for r in receipts
        ],
        "decisions": [
            {
                "decision": d.decision,
                "expected_version": d.expected_request_version,
                "verified_transfer_amount_rial": d.verified_transfer_amount_rial,
                "bonus_amount_rial": d.bonus_amount_rial,
                "reason_code": d.reason_code,
                "internal_note": d.internal_note,
                "customer_message": d.customer_message,
                "created_at": d.created_at,
            }
            for d in decisions
        ],
        "messages": [
            {
                "reference": m.reference,
                "visibility": m.visibility,
                "body": m.body,
                "created_at": m.created_at,
            }
            for m in messages
        ],
        "notifications": [
            {
                "event_reference": e.event_reference,
                "event_type": e.event_type,
                "status": e.status,
                "attempts": e.attempts,
                "available_at": e.available_at,
                "sent_at": e.sent_at,
            }
            for e in events
        ],
    }


@admin_router.get("")
def admin_queue(
    _: Annotated[AdminModel, Depends(require_perm("manual_topups.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    order: Literal["newest", "oldest"] = "newest",
    limit: Annotated[int, Query(ge=1, le=MAX_READ_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> dict[str, object]:
    stmt = select(ManualTopupRequestModel)
    if status_filter:
        stmt = stmt.where(ManualTopupRequestModel.status.in_(status_filter))
    ordering = (
        (ManualTopupRequestModel.created_at.desc(), ManualTopupRequestModel.id.desc())
        if order == "newest"
        else (ManualTopupRequestModel.created_at, ManualTopupRequestModel.id)
    )
    rows = db.scalars(stmt.order_by(*ordering).limit(limit).offset(offset)).all()
    return {"items": [_admin_dto(db, row) for row in rows], "limit": limit, "offset": offset}


@admin_router.get("/{reference}")
def admin_detail(
    reference: str,
    _: Annotated[AdminModel, Depends(require_perm("manual_topups.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    return _admin_dto(db, _request(db, reference))


@admin_router.get("/{reference}/receipt")
def admin_receipt(
    reference: str,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("manual_topups.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    row = _request(db, reference)
    _audit(db, admin.id, "manual_topup.receipt.accessed", row, request)
    return _stream(db, row, settings)


async def _decision(
    reference: str,
    target: ManualTopupStatus,
    event: str,
    body: VersionedDecision,
    request: Request,
    admin: AdminModel,
    db: Session,
    settings: Settings,
    limiter: RateLimiter,
    key: str | None,
    csrf: str | None,
    authorization: str | None,
) -> dict[str, object]:
    _enabled(settings)
    session = _admin_session(db, settings, authorization)
    _admin_csrf(session, csrf)
    await _rate(limiter, "manual-topup-decision", admin.id, 30)
    safe = customer_safe_text(body.customer_message)
    fp = _fingerprint(body.model_dump())
    prior = _idem(
        db, scope="REQUEST", scope_id=reference, operation=target.value, key=key, fingerprint=fp
    )
    row = _request(db, reference, lock=not bool(prior))
    if prior:
        return _admin_dto(db, row)
    if row.version != body.expected_version:
        raise _error(409, "STALE_VERSION")
    try:
        require_transition(ManualTopupStatus(row.status), target)
    except ValueError as exc:
        raise _error(409, "INVALID_TRANSITION") from exc
    decision = ManualTopupDecisionModel(
        request_id=row.id,
        decision=target.value,
        admin_id=admin.id,
        expected_request_version=body.expected_version,
        reason_code=body.reason_code,
        internal_note=body.internal_note,
        customer_message=safe,
    )
    db.add(decision)
    msg = _message(db, row, admin.id, safe)
    row.status = target.value
    row.customer_message = safe
    row.reason_code = body.reason_code
    row.version += 1
    if target == ManualTopupStatus.REJECTED:
        row.rejected_by_admin_id = admin.id
        row.decided_at = _now()
    _outbox(db, row, event, decision.id)
    _audit(db, admin.id, f"manual_topup.{target.value.lower()}", row, request)
    _idem(
        db,
        scope="REQUEST",
        scope_id=reference,
        operation=target.value,
        key=key,
        fingerprint=fp,
        result=msg.reference,
    )
    return _admin_dto(db, row)


@admin_router.post("/{reference}/request-resubmission")
async def request_resubmission(
    reference: str,
    body: VersionedDecision,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("manual_topups.review"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    return await _decision(
        reference,
        ManualTopupStatus.NEEDS_RESUBMISSION,
        "NEEDS_RESUBMISSION",
        body,
        request,
        admin,
        db,
        settings,
        limiter,
        key,
        csrf,
        authorization,
    )


@admin_router.post("/{reference}/reject")
async def reject(
    reference: str,
    body: VersionedDecision,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("manual_topups.review"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    return await _decision(
        reference,
        ManualTopupStatus.REJECTED,
        "REJECTED",
        body,
        request,
        admin,
        db,
        settings,
        limiter,
        key,
        csrf,
        authorization,
    )


@admin_router.post("/{reference}/messages")
async def admin_message(
    reference: str,
    body: AdminMessage,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("manual_topups.message"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _enabled(settings)
    session = _admin_session(db, settings, authorization)
    _admin_csrf(session, csrf)
    await _rate(limiter, "manual-topup-message", admin.id, 60)
    safe = customer_safe_text(body.body)
    fp = _fingerprint(body.model_dump())
    prior = _idem(
        db, scope="REQUEST", scope_id=reference, operation="MESSAGE", key=key, fingerprint=fp
    )
    row = _request(db, reference)
    if prior:
        return _admin_dto(db, row)
    message = _message(db, row, admin.id, safe)
    _outbox(db, row, "ADMIN_MESSAGE", message.reference)
    _audit(db, admin.id, "manual_topup.message.created", row, request)
    _idem(
        db,
        scope="REQUEST",
        scope_id=reference,
        operation="MESSAGE",
        key=key,
        fingerprint=fp,
        result=message.reference,
    )
    return _admin_dto(db, row)


@admin_router.post("/{reference}/strong-confirmation")
async def issue_strong_confirmation(
    reference: str,
    body: StrongConfirmation,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("manual_topups.review"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    _enabled(settings)
    session = _admin_session(db, settings, authorization)
    _admin_csrf(session, csrf)
    await _rate(limiter, "manual-topup-strong-confirm", admin.id, 5)
    if body.request_reference != reference:
        raise _error(400, "CONFIRMATION_BINDING_MISMATCH")
    from platform_api.admin_auth.routes import admin_auth_service

    service = admin_auth_service(db, settings)
    if not service.verify_strong_confirmation(
        admin.id, body.current_password, body.totp_code, now=_now()
    ):
        raise _error(403, "STRONG_CONFIRMATION_FAILED")
    token = secrets.token_urlsafe(48)
    binding = _fingerprint(
        {
            "admin": admin.id,
            "session": session.id,
            "purpose": "MANUAL_TOPUP_APPROVAL",
            "reference": reference,
            "override": body.override_acknowledged,
        }
    )
    db.add(
        ManualTopupIdempotencyModel(
            scope="CONFIRMATION",
            scope_id=session.id,
            operation="MANUAL_TOPUP_APPROVAL",
            key_hash=_hash(token),
            request_fingerprint=binding,
            result_reference=reference,
            expires_at=_now() + timedelta(minutes=5),
        )
    )
    _audit(
        db, admin.id, "manual_topup.strong_confirmation.issued", _request(db, reference), request
    )
    return {"strong_confirmation_token": token, "expires_in_seconds": "300"}


def _consume_confirmation(
    db: Session,
    admin: AdminModel,
    session: AdminSessionModel,
    reference: str,
    token: str,
    override: bool,
) -> None:
    row = db.scalar(
        select(ManualTopupIdempotencyModel)
        .where(
            ManualTopupIdempotencyModel.scope == "CONFIRMATION",
            ManualTopupIdempotencyModel.scope_id == session.id,
            ManualTopupIdempotencyModel.operation == "MANUAL_TOPUP_APPROVAL",
            ManualTopupIdempotencyModel.key_hash == _hash(token),
        )
        .with_for_update()
    )
    binding = _fingerprint(
        {
            "admin": admin.id,
            "session": session.id,
            "purpose": "MANUAL_TOPUP_APPROVAL",
            "reference": reference,
            "override": override,
        }
    )
    if (
        row is None
        or row.expires_at.replace(tzinfo=UTC) < _now()
        or row.request_fingerprint != binding
        or row.result_reference != reference
    ):
        raise _error(403, "STRONG_CONFIRMATION_INVALID")
    db.delete(row)
    db.flush()


@admin_router.post("/{reference}/approve")
async def approve(
    reference: str,
    body: Approval,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("manual_topups.review"))],
    _: Annotated[AdminModel, Depends(require_perm("wallets.adjust"))],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _enabled(settings)
    session = _admin_session(db, settings, authorization)
    _admin_csrf(session, csrf)
    await _rate(limiter, "manual-topup-approval", admin.id, 20)
    verified, bonus, total = approval_amounts(
        body.verified_transfer_amount_rial, body.bonus_amount_rial
    )
    safe_message = customer_safe_text(body.customer_message) if body.customer_message else None
    fp = _fingerprint(body.model_dump(exclude={"strong_confirmation_token"}))
    prior = _idem(
        db, scope="REQUEST", scope_id=reference, operation="APPROVE", key=key, fingerprint=fp
    )
    row = _request(db, reference, lock=not bool(prior))
    if prior:
        return _admin_dto(db, row)
    if row.version != body.expected_version:
        raise _error(409, "STALE_VERSION")
    try:
        require_transition(ManualTopupStatus(row.status), ManualTopupStatus.APPROVED)
    except ValueError as exc:
        raise _error(409, "INVALID_TRANSITION") from exc
    if (
        not row.current_receipt_id
        or db.get(ManualTopupReceiptModel, row.current_receipt_id) is None
    ):
        raise _error(409, "CURRENT_RECEIPT_REQUIRED")
    override = verified != row.requested_amount_rial or bonus > 0
    if override:
        if "manual_topups.override_amount" not in active_permissions(db, admin.id):
            raise _error(403, "OVERRIDE_PERMISSION_REQUIRED")
        if not body.reason_code or not body.override_acknowledged:
            raise _error(422, "OVERRIDE_ACKNOWLEDGEMENT_REQUIRED")
    _consume_confirmation(
        db, admin, session, reference, body.strong_confirmation_token, body.override_acknowledged
    )
    wallet = db.scalar(select(WalletModel).where(WalletModel.id == row.wallet_id).with_for_update())
    if wallet is None or wallet.status != "ACTIVE":
        raise _error(409, "ACTIVE_WALLET_REQUIRED")
    projection = wallet_projection(db, wallet.id, lock=True)
    if projection.posted_balance_rial + total > wallet_policy(db).maximum_wallet_balance_rial:
        raise _error(409, "MAXIMUM_BALANCE_EXCEEDED")
    cash = post_wallet_adjustment(
        db,
        wallet,
        "ADMIN_CREDIT",
        verified,
        "CASH",
        admin.id,
        request,
        "MANUAL_CARD_TRANSFER_APPROVED",
    )
    bonus_journal = (
        post_wallet_adjustment(
            db,
            wallet,
            "ADMIN_CREDIT",
            bonus,
            "ADMIN_GRANT",
            admin.id,
            request,
            "MANUAL_CARD_TRANSFER_BONUS",
        )
        if bonus
        else None
    )
    decision = ManualTopupDecisionModel(
        request_id=row.id,
        decision="APPROVED",
        admin_id=admin.id,
        expected_request_version=body.expected_version,
        verified_transfer_amount_rial=verified,
        bonus_amount_rial=bonus,
        reason_code=body.reason_code or "MANUAL_CARD_TRANSFER_APPROVED",
        internal_note=body.internal_note,
        customer_message=safe_message,
        cash_journal_entry_id=cash.id,
        bonus_journal_entry_id=bonus_journal.id if bonus_journal else None,
    )
    db.add(decision)
    row.status = "APPROVED"
    row.verified_transfer_amount_rial = verified
    row.bonus_amount_rial = bonus
    row.total_credited_amount_rial = total
    row.cash_journal_entry_id = cash.id
    row.bonus_journal_entry_id = bonus_journal.id if bonus_journal else None
    row.decided_at = _now()
    row.approved_by_admin_id = admin.id
    row.reason_code = decision.reason_code
    row.customer_message = safe_message
    row.version += 1
    if safe_message:
        _message(db, row, admin.id, safe_message)
    _outbox(db, row, "APPROVED", decision.id)
    _audit(db, admin.id, "manual_topup.approved", row, request)
    _idem(
        db,
        scope="REQUEST",
        scope_id=reference,
        operation="APPROVE",
        key=key,
        fingerprint=fp,
        result=reference,
    )
    db.flush()
    return _admin_dto(db, row)
