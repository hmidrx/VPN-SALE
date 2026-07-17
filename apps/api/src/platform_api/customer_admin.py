from __future__ import annotations

import csv
import io
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from vpnsale_domain.identity import UserStatus, ensure_transition, sanitize_metadata

from platform_api.customer_admin_models import (
    CustomerAdjustmentRequestModel,
    CustomerBulkItemModel,
    CustomerBulkJobModel,
    CustomerExportJobModel,
    CustomerNoteHistoryModel,
    CustomerNoteModel,
    CustomerSavedViewModel,
    CustomerTagAssignmentModel,
    CustomerTagModel,
)
from platform_api.database import get_db_session
from platform_api.identity.models import (
    AdminModel,
    AuditLogModel,
    CustomerProfileModel,
    CustomerSessionModel,
    SecurityEventModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.management import require_perm
from platform_api.wallet import (
    build_wallet_admin_view,
    ensure_customer_wallet,
    post_admin_wallet_adjustment,
)
from platform_api.wallet_models import JournalEntryModel, WalletModel, WalletReservationModel

router = APIRouter(prefix="/api/v1/admin/customers", tags=["admin-customers"])
MAX_PAGE = 100
MAX_EXPORT_ROWS = 5000
MAX_BULK = 500
ALLOWED_EXPORT_FIELDS = {
    "customer_reference",
    "display_name",
    "account_status",
    "telegram_username",
    "created_at",
    "wallet_status",
    "tags",
}


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class ReasonCommand(BaseModel):
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    note: str | None = Field(default=None, max_length=500)
    expected_version: int = Field(ge=1)


class NoteIn(BaseModel):
    note_type: str = Field(
        pattern=r"^(GENERAL|FINANCIAL|SECURITY|OPERATIONS|SUPPORT_PREPARATION|COMPLIANCE)$"
    )
    body: str = Field(min_length=1, max_length=2000)
    pinned: bool = False


class TagIn(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    name_i18n: dict[str, str]
    description_i18n: dict[str, str] = Field(default_factory=dict)
    color_token: str = Field(pattern=r"^(blue|green|amber|red|purple|slate)$")


class SavedViewIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    visibility: str = Field(default="PERSONAL", pattern=r"^(PERSONAL|SHARED)$")
    filters: dict[str, object] = Field(default_factory=dict)
    sort: str = Field(default="created_desc", pattern=r"^(created_desc|created_asc|activity_desc)$")
    columns: list[str] = Field(default_factory=list, max_length=20)


class AdjustmentIn(BaseModel):
    direction: str = Field(pattern=r"^(CREDIT|DEBIT)$")
    bucket_type: str = Field(pattern=r"^(PROMOTIONAL|ADMIN_GRANT|GIFT|REFERRAL|CASH)$")
    amount_rial: int = Field(gt=0, le=2_000_000_000)
    purpose: str = Field(
        pattern=r"^(COMPENSATION|PROMOTIONAL_CREDIT|ADMINISTRATIVE_CORRECTION|CUSTOMER_SERVICE_CREDIT|CASH_CORRECTION)$"
    )
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    explanation: str = Field(min_length=1, max_length=500)
    expected_wallet_version: int = Field(ge=1)


class ApprovalIn(BaseModel):
    amount_rial: int = Field(gt=0)
    bucket_type: str
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")


class ExportIn(BaseModel):
    filters: dict[str, object] = Field(default_factory=dict)
    fields: list[str] = Field(min_length=1, max_length=20)
    file_format: str = Field(default="CSV", pattern=r"^CSV$")


class BulkIn(BaseModel):
    operation: str = Field(
        pattern=r"^(ADD_TAG|REMOVE_TAG|SUSPEND|RESTORE|BLOCK|REVOKE_SESSIONS|FREEZE_WALLET|UNFREEZE_WALLET|NON_CASH_ADJUSTMENT|EXPORT)$"
    )
    customer_references: list[str] = Field(min_length=1, max_length=MAX_BULK)
    parameters: dict[str, object] = Field(default_factory=dict)
    reason_code: str = Field(pattern=r"^[A-Z0-9_]{3,64}$")
    dry_run: bool = True


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _hash(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def _cursor(dt: datetime, ident: str) -> str:
    return urlsafe_b64encode(f"{dt.isoformat()}|{ident}".encode()).decode()


def _decode_cursor(v: str | None) -> tuple[datetime, str] | None:
    if not v:
        return None
    raw = urlsafe_b64decode(v.encode()).decode()
    dt, ident = raw.split("|", 1)
    return datetime.fromisoformat(dt), ident


def _audit(
    db: Session,
    admin_id: str,
    code: str,
    target_type: str,
    target_id: str | None,
    request: Request,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin_id,
            target_type=target_type,
            target_id=target_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            metadata_=sanitize_metadata(metadata or {}),
        )
    )


def _security(
    db: Session,
    admin_id: str,
    code: str,
    request: Request,
    severity: str = "WARNING",
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        SecurityEventModel(
            actor_type="admin",
            actor_id=admin_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            severity=severity,
            status="OPEN",
            metadata_=sanitize_metadata(metadata or {}),
        )
    )


def _limit(limit: int | None) -> int:
    return min(max(limit or 50, 1), MAX_PAGE)


def _mask_telegram(v: int | None) -> str | None:
    if v is None:
        return None
    s = str(v)
    return f"{s[:2]}***{s[-2:]}" if len(s) > 4 else "***"


def _filter_text(filters: dict[str, object], key: str) -> str | None:
    value = filters.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _filter_positive_int(filters: dict[str, object], key: str) -> int | None:
    value = filters.get(key)
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdecimal():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _journal_view(row: JournalEntryModel) -> dict[str, str | None]:
    return {
        "journal_entry_reference": row.id,
        "operation_code": row.operation_code,
        "posted_at": _iso_datetime(row.posted_at),
        "ledger_link": f"/api/v1/admin/management/ledger/journals/{row.id}",
    }


def _customer_row(db: Session, u: UserModel, can_security: bool = False) -> dict[str, Any]:
    p = db.get(CustomerProfileModel, u.id)
    tg = db.scalar(select(TelegramAccountModel).where(TelegramAccountModel.user_id == u.id))
    wallet = db.scalar(select(WalletModel).where(WalletModel.customer_id == u.id))
    tags = db.execute(
        select(CustomerTagModel.code, CustomerTagModel.name_i18n, CustomerTagModel.color_token)
        .join(CustomerTagAssignmentModel, CustomerTagAssignmentModel.tag_id == CustomerTagModel.id)
        .where(
            CustomerTagAssignmentModel.customer_id == u.id,
            CustomerTagAssignmentModel.removed_at.is_(None),
        )
    ).all()
    sessions = (
        db.scalar(
            select(func.count())
            .select_from(CustomerSessionModel)
            .where(CustomerSessionModel.user_id == u.id, CustomerSessionModel.revoked_at.is_(None))
        )
        or 0
    )
    warnings: list[str] = []
    if u.status in {"SUSPENDED", "BLOCKED"}:
        warnings.append("account_restricted")
    if wallet and wallet.status == "FROZEN":
        warnings.append("wallet_frozen")
    return {
        "customer_reference": u.id,
        "display_name": p.display_name if p else None,
        "account_status": u.status,
        "version": int(getattr(u, "updated_at", datetime.now(UTC)).timestamp()),
        "locale": p.locale if p else tg.language_code if tg else None,
        "created_at": u.created_at.isoformat(),
        "last_activity_at": tg.last_seen_at.isoformat() if tg else None,
        "telegram": {
            "id": tg.telegram_user_id
            if can_security and tg
            else _mask_telegram(tg.telegram_user_id if tg else None),
            "username": tg.username if tg else None,
            "display_name": " ".join(
                x for x in [tg.first_name if tg else None, tg.last_name if tg else None] if x
            )
            or None,
        },
        "wallet": build_wallet_admin_view(db, wallet) if wallet else None,
        "active_session_count": sessions,
        "tags": [{"code": c, "name_i18n": n, "color_token": color} for c, n, color in tags],
        "risk_indicators": warnings,
    }


def _filter_stmt(db: Session, filters: dict[str, object]) -> Any:
    stmt = select(UserModel).where(UserModel.status.in_([s.value for s in UserStatus]))
    ref = _filter_text(filters, "customer_reference")
    if ref is not None:
        stmt = stmt.where(UserModel.id == ref)
    status = _filter_text(filters, "account_status")
    if status is not None:
        stmt = stmt.where(UserModel.status == status)
    tg_id = _filter_positive_int(filters, "telegram_id")
    if tg_id is not None:
        stmt = stmt.join(TelegramAccountModel, TelegramAccountModel.user_id == UserModel.id).where(
            TelegramAccountModel.telegram_user_id == tg_id
        )
    username = _filter_text(filters, "telegram_username")
    if username is not None:
        stmt = stmt.join(TelegramAccountModel, TelegramAccountModel.user_id == UserModel.id).where(
            TelegramAccountModel.username == username.removeprefix("@").casefold()
        )
    name = _filter_text(filters, "display_name")
    if name is not None:
        stmt = stmt.join(CustomerProfileModel, CustomerProfileModel.user_id == UserModel.id).where(
            CustomerProfileModel.display_name.ilike(f"%{name[:80]}%")
        )
    tag = _filter_text(filters, "tag")
    if tag is not None:
        stmt = (
            stmt.join(
                CustomerTagAssignmentModel, CustomerTagAssignmentModel.customer_id == UserModel.id
            )
            .join(CustomerTagModel, CustomerTagModel.id == CustomerTagAssignmentModel.tag_id)
            .where(CustomerTagModel.code == tag, CustomerTagAssignmentModel.removed_at.is_(None))
        )
    return stmt


@router.get("", response_model=Page)
def list_customers(
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.read"))],
    request: Request,
    limit: int | None = None,
    cursor: str | None = None,
    account_status: str | None = None,
    telegram_username: str | None = None,
    display_name: str | None = None,
) -> Page:
    filters = {
        "account_status": account_status,
        "telegram_username": telegram_username,
        "display_name": display_name,
    }
    stmt = _filter_stmt(db, {k: v for k, v in filters.items() if v})
    cur = _decode_cursor(cursor)
    if cur:
        stmt = stmt.where(
            or_(
                UserModel.created_at < cur[0],
                and_(UserModel.created_at == cur[0], UserModel.id < cur[1]),
            )
        )
    n = _limit(limit)
    rows = db.scalars(
        stmt.order_by(UserModel.created_at.desc(), UserModel.id.desc()).limit(n + 1)
    ).all()
    _audit(db, admin.id, "customer.directory_viewed", "customer", None, request, {"limit": n})
    return Page(
        items=[_customer_row(db, r) for r in rows[:n]],
        next_cursor=_cursor(rows[n - 1].created_at, rows[n - 1].id) if len(rows) > n else None,
    )


@router.get("/{customer_id}")
def customer_detail(
    customer_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.read"))],
    request: Request,
) -> dict[str, Any]:
    u = db.get(UserModel, customer_id)
    if not u:
        raise HTTPException(404)
    wallet = db.scalar(select(WalletModel).where(WalletModel.customer_id == customer_id))
    sessions: list[CustomerSessionModel] = list(
        db.scalars(
            select(CustomerSessionModel)
            .where(CustomerSessionModel.user_id == customer_id)
            .order_by(CustomerSessionModel.created_at.desc())
            .limit(100)
        ).all()
    )
    journals: list[JournalEntryModel] = []
    if wallet is not None:
        journals = list(
            db.scalars(
                select(JournalEntryModel)
                .where(JournalEntryModel.wallet_id == wallet.id)
                .order_by(JournalEntryModel.posted_at.desc())
                .limit(50)
            ).all()
        )
    notes: list[CustomerNoteModel] = list(
        db.scalars(
            select(CustomerNoteModel)
            .where(
                CustomerNoteModel.customer_id == customer_id,
                CustomerNoteModel.archived_at.is_(None),
            )
            .order_by(CustomerNoteModel.pinned.desc(), CustomerNoteModel.created_at.desc())
        ).all()
    )
    _audit(db, admin.id, "customer.profile_viewed", "customer", customer_id, request)
    return {
        "overview": _customer_row(db, u, can_security=True),
        "security": {
            "sessions": [
                {
                    "session_reference": s.id,
                    "device_label": s.device_label,
                    "created_at": s.created_at.isoformat(),
                    "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
                    "idle_expires_at": s.idle_expires_at.isoformat(),
                    "absolute_expires_at": s.absolute_expires_at.isoformat(),
                    "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
                    "suspicious": bool(s.reuse_detected_at),
                }
                for s in sessions
            ]
        },
        "wallet": build_wallet_admin_view(db, wallet) if wallet else None,
        "transactions": [_journal_view(j) for j in journals],
        "reservations": [
            {"reservation_reference": r.id, "amount_rial": r.amount_rial, "status": r.status}
            for r in db.scalars(
                select(WalletReservationModel).where(
                    WalletReservationModel.customer_id == customer_id
                )
            ).all()
        ],
        "commerce": {"orders": [], "invoices": [], "payments": [], "refunds": []},
        "notes": [
            {
                "note_reference": n.id,
                "note_type": n.note_type,
                "body": n.body,
                "pinned": n.pinned,
                "version": n.version,
            }
            for n in notes
        ],
        "activity": [],
    }


@router.post("/{customer_id}/lifecycle/{command}")
def lifecycle(
    customer_id: str,
    command: str,
    body: ReasonCommand,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.manage_status"))],
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    mapping = {
        "activate": "ACTIVE",
        "suspend": "SUSPENDED",
        "restore": "ACTIVE",
        "block": "BLOCKED",
        "deactivate": "DEACTIVATED",
        "reactivate": "ACTIVE",
    }
    if command not in mapping:
        raise HTTPException(404)
    u = db.get(UserModel, customer_id)
    if not u:
        raise HTTPException(404)
    if body.expected_version != int(u.updated_at.timestamp()):
        raise HTTPException(409, detail={"code": "STALE_VERSION"})
    try:
        ensure_transition(UserStatus(u.status), UserStatus(mapping[command]))
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "ILLEGAL_TRANSITION"}) from exc
    u.status = mapping[command]
    u.updated_at = datetime.now(UTC)
    if u.status in {"SUSPENDED", "BLOCKED", "DEACTIVATED"}:
        for s in db.scalars(
            select(CustomerSessionModel).where(
                CustomerSessionModel.user_id == customer_id,
                CustomerSessionModel.revoked_at.is_(None),
            )
        ).all():
            s.revoked_at = datetime.now(UTC)
            s.revocation_reason = body.reason_code
    _audit(
        db,
        admin.id,
        f"customer.{command}",
        "customer",
        customer_id,
        request,
        {"reason_code": body.reason_code},
    )
    return _customer_row(db, u, can_security=True)


@router.get("/{customer_id}/sessions")
def sessions(
    customer_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("customers.manage_security"))],
) -> dict[str, Any]:
    rows = db.scalars(
        select(CustomerSessionModel)
        .where(CustomerSessionModel.user_id == customer_id)
        .order_by(CustomerSessionModel.created_at.desc())
    ).all()
    return {
        "items": [
            {
                "session_reference": s.id,
                "device_label": s.device_label,
                "revoked_at": s.revoked_at.isoformat() if s.revoked_at else None,
            }
            for s in rows
        ]
    }


@router.post("/{customer_id}/sessions/{session_id}/revoke")
def revoke_session(
    customer_id: str,
    session_id: str,
    body: ReasonCommand,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.manage_security"))],
    request: Request,
) -> dict[str, str]:
    s = db.get(CustomerSessionModel, session_id)
    if not s or s.user_id != customer_id:
        raise HTTPException(404)
    if not s.revoked_at:
        s.revoked_at = datetime.now(UTC)
        s.revocation_reason = body.reason_code
    _audit(
        db,
        admin.id,
        "customer.session_revoked",
        "customer_session",
        s.id,
        request,
        {"customer_id": customer_id},
    )
    return {"session_reference": s.id, "status": "REVOKED"}


@router.post("/{customer_id}/sessions/revoke-all")
def revoke_all(
    customer_id: str,
    body: ReasonCommand,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.manage_security"))],
    request: Request,
) -> dict[str, int]:
    count = 0
    for s in db.scalars(
        select(CustomerSessionModel).where(
            CustomerSessionModel.user_id == customer_id, CustomerSessionModel.revoked_at.is_(None)
        )
    ).all():
        s.revoked_at = datetime.now(UTC)
        s.revocation_reason = body.reason_code
        count += 1
    _audit(
        db,
        admin.id,
        "customer.sessions_revoked",
        "customer",
        customer_id,
        request,
        {"count": count},
    )
    return {"revoked_count": count}


@router.post("/{customer_id}/wallet/freeze")
def freeze_wallet(
    customer_id: str,
    body: ReasonCommand,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customer_wallets.freeze"))],
    request: Request,
) -> dict[str, Any]:
    wallet = ensure_customer_wallet(db, customer_id)
    wallet.status = "FROZEN"
    wallet.updated_at = datetime.now(UTC)
    _audit(
        db,
        admin.id,
        "customer.wallet_frozen",
        "wallet",
        wallet.id,
        request,
        {"reason_code": body.reason_code},
    )
    return build_wallet_admin_view(db, wallet)


@router.post("/{customer_id}/wallet/unfreeze")
def unfreeze_wallet(
    customer_id: str,
    body: ReasonCommand,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customer_wallets.freeze"))],
    request: Request,
) -> dict[str, Any]:
    wallet = ensure_customer_wallet(db, customer_id)
    wallet.status = "ACTIVE"
    wallet.updated_at = datetime.now(UTC)
    _audit(
        db,
        admin.id,
        "customer.wallet_unfrozen",
        "wallet",
        wallet.id,
        request,
        {"reason_code": body.reason_code},
    )
    return build_wallet_admin_view(db, wallet)


@router.post("/{customer_id}/adjustments")
def request_adjustment(
    customer_id: str,
    body: AdjustmentIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customer_wallets.adjust"))],
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    if body.bucket_type == "CASH":
        # Cash adjustments are high-risk and remain pending for approval.
        pass
    wallet = ensure_customer_wallet(db, customer_id)
    high = body.amount_rial >= 50_000_000 or body.bucket_type == "CASH" or wallet.status == "FROZEN"
    adj = db.scalar(
        select(CustomerAdjustmentRequestModel).where(
            CustomerAdjustmentRequestModel.requested_by_admin_id == admin.id,
            CustomerAdjustmentRequestModel.idempotency_key_hash == _hash(idempotency_key),
        )
    )
    if adj:
        return {"adjustment_reference": adj.id, "status": adj.status, "high_risk": adj.high_risk}
    adj = CustomerAdjustmentRequestModel(
        customer_id=customer_id,
        wallet_id=wallet.id,
        direction=body.direction,
        bucket_type=body.bucket_type,
        amount_rial=body.amount_rial,
        purpose=body.purpose,
        reason_code=body.reason_code,
        explanation=body.explanation,
        status="PENDING_APPROVAL" if high else "APPROVED",
        high_risk=high,
        requested_by_admin_id=admin.id,
        idempotency_key_hash=_hash(idempotency_key),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db.add(adj)
    db.flush()
    if not high:
        je = post_admin_wallet_adjustment(
            db,
            wallet,
            "ADMIN_CREDIT" if body.direction == "CREDIT" else "ADMIN_DEBIT",
            body.amount_rial,
            body.bucket_type,
            admin.id,
            request,
            body.reason_code,
        )
        adj.journal_entry_id = je.id
        adj.status = "EXECUTED"
    _audit(
        db,
        admin.id,
        "customer.adjustment_requested",
        "customer",
        customer_id,
        request,
        {"amount_rial": body.amount_rial, "high_risk": high},
    )
    return {
        "adjustment_reference": adj.id,
        "status": adj.status,
        "high_risk": adj.high_risk,
        "journal_entry_reference": adj.journal_entry_id,
    }


@router.post("/adjustments/{adjustment_id}/approve")
def approve_adjustment(
    adjustment_id: str,
    body: ApprovalIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customer_wallets.approve_adjustment"))],
    request: Request,
) -> dict[str, Any]:
    adj = db.get(CustomerAdjustmentRequestModel, adjustment_id)
    if not adj:
        raise HTTPException(404)
    if adj.requested_by_admin_id == admin.id:
        _security(
            db,
            admin.id,
            "customer_adjustment.self_approval_denied",
            request,
            metadata={"adjustment_id": adjustment_id},
        )
        raise HTTPException(403, detail={"code": "SELF_APPROVAL_DENIED"})
    if adj.status not in {"PENDING_APPROVAL", "APPROVED"} or adj.expires_at.replace(
        tzinfo=UTC
    ) < datetime.now(UTC):
        raise HTTPException(409)
    if adj.amount_rial != body.amount_rial or adj.bucket_type != body.bucket_type:
        raise HTTPException(409, detail={"code": "CONFIRMATION_MISMATCH"})
    wallet = db.get(WalletModel, adj.wallet_id)
    if not wallet:
        raise HTTPException(404)
    if adj.journal_entry_id:
        return {
            "adjustment_reference": adj.id,
            "status": adj.status,
            "journal_entry_reference": adj.journal_entry_id,
        }
    je = post_admin_wallet_adjustment(
        db,
        wallet,
        "ADMIN_CREDIT" if adj.direction == "CREDIT" else "ADMIN_DEBIT",
        adj.amount_rial,
        adj.bucket_type,
        admin.id,
        request,
        adj.reason_code,
    )
    adj.approved_by_admin_id = admin.id
    adj.journal_entry_id = je.id
    adj.status = "EXECUTED"
    adj.version += 1
    _audit(
        db,
        admin.id,
        "customer.adjustment_approved",
        "customer_adjustment",
        adj.id,
        request,
        {"journal_id": je.id},
    )
    return {"adjustment_reference": adj.id, "status": adj.status, "journal_entry_reference": je.id}


@router.post("/{customer_id}/notes")
def add_note(
    customer_id: str,
    body: NoteIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.notes.manage"))],
    request: Request,
) -> dict[str, Any]:
    if "<" in body.body or "script" in body.body.casefold():
        _security(
            db,
            admin.id,
            "customer_note.unsafe_content",
            request,
            metadata={"customer_id": customer_id},
        )
        raise HTTPException(422)
    n = CustomerNoteModel(
        customer_id=customer_id,
        note_type=body.note_type,
        body=body.body,
        pinned=body.pinned,
        created_by_admin_id=admin.id,
    )
    db.add(n)
    db.flush()
    db.add(
        CustomerNoteHistoryModel(note_id=n.id, version=1, body=n.body, changed_by_admin_id=admin.id)
    )
    _audit(db, admin.id, "customer.note_added", "customer", customer_id, request)
    return {"note_reference": n.id, "version": n.version}


@router.post("/tags")
def create_tag(
    body: TagIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.tags.manage"))],
    request: Request,
) -> dict[str, Any]:
    tag = CustomerTagModel(
        code=body.code,
        name_i18n=body.name_i18n,
        description_i18n=body.description_i18n,
        color_token=body.color_token,
        created_by_admin_id=admin.id,
    )
    db.add(tag)
    db.flush()
    _audit(db, admin.id, "customer_tag.created", "customer_tag", tag.id, request)
    return {"tag_reference": tag.id, "code": tag.code}


@router.post("/{customer_id}/tags/{tag_code}")
def assign_tag(
    customer_id: str,
    tag_code: str,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.tags.manage"))],
    request: Request,
) -> dict[str, str]:
    tag = db.scalar(
        select(CustomerTagModel).where(
            CustomerTagModel.code == tag_code, CustomerTagModel.active.is_(True)
        )
    )
    if not tag:
        raise HTTPException(404)
    row = db.scalar(
        select(CustomerTagAssignmentModel).where(
            CustomerTagAssignmentModel.customer_id == customer_id,
            CustomerTagAssignmentModel.tag_id == tag.id,
        )
    )
    if row:
        row.removed_at = None
    else:
        db.add(
            CustomerTagAssignmentModel(
                customer_id=customer_id, tag_id=tag.id, assigned_by_admin_id=admin.id
            )
        )
    _audit(
        db, admin.id, "customer.tag_assigned", "customer", customer_id, request, {"tag": tag_code}
    )
    return {"status": "ASSIGNED"}


@router.post("/saved-views")
def save_view(
    body: SavedViewIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.read"))],
    request: Request,
) -> dict[str, str]:
    allowed = {"customer_reference", "account_status", "telegram_username", "display_name", "tag"}
    if any(k not in allowed for k in body.filters):
        raise HTTPException(422)
    v = CustomerSavedViewModel(
        owner_admin_id=admin.id,
        name=body.name,
        visibility=body.visibility,
        filters=body.filters,
        sort=body.sort,
        columns={"visible": body.columns},
    )
    db.add(v)
    db.flush()
    _audit(db, admin.id, "customer.saved_view_created", "customer_saved_view", v.id, request)
    return {"saved_view_reference": v.id}


@router.post("/exports")
def create_export(
    body: ExportIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.export"))],
    request: Request,
) -> dict[str, Any]:
    fields = [f for f in body.fields if f in ALLOWED_EXPORT_FIELDS]
    if len(fields) != len(body.fields):
        raise HTTPException(422)
    rows = db.scalars(
        _filter_stmt(db, body.filters)
        .order_by(UserModel.created_at.desc())
        .limit(MAX_EXPORT_ROWS + 1)
    ).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise HTTPException(422, detail={"code": "EXPORT_TOO_LARGE"})
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for u in rows:
        r = _customer_row(db, u)
        writer.writerow({k: _csv_safe(str(r.get(k, ""))) for k in fields})
    raw_ref = (
        urlsafe_b64encode(sha256(f"{admin.id}{datetime.now(UTC).isoformat()}".encode()).digest())
        .decode()
        .rstrip("=")
    )
    job = CustomerExportJobModel(
        requested_by_admin_id=admin.id,
        status="COMPLETED",
        file_format="CSV",
        filters=body.filters,
        fields={"fields": fields},
        row_count=len(rows),
        download_reference_hash=_hash(raw_ref),
        content=output.getvalue(),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
        completed_at=datetime.now(UTC),
    )
    db.add(job)
    db.flush()
    _audit(
        db,
        admin.id,
        "customer.export_created",
        "customer_export",
        job.id,
        request,
        {"row_count": len(rows)},
    )
    return {
        "export_reference": job.id,
        "status": job.status,
        "download_reference": raw_ref,
        "expires_at": job.expires_at.isoformat(),
    }


def _csv_safe(value: str) -> str:
    return "'" + value if value and value[0] in "=+-@\t\r" else value


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str,
    download_reference: str,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.export"))],
    request: Request,
) -> Response:
    job = db.get(CustomerExportJobModel, export_id)
    if (
        not job
        or job.requested_by_admin_id != admin.id
        or job.download_reference_hash != _hash(download_reference)
        or job.expires_at.replace(tzinfo=UTC) < datetime.now(UTC)
    ):
        raise HTTPException(404)
    _audit(db, admin.id, "customer.export_downloaded", "customer_export", job.id, request)
    return Response(
        job.content or "",
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=customers-{job.id}.csv"},
    )


@router.post("/bulk")
def create_bulk(
    body: BulkIn,
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("customers.bulk.manage"))],
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> dict[str, Any]:
    existing = db.scalar(
        select(CustomerBulkJobModel).where(
            CustomerBulkJobModel.requested_by_admin_id == admin.id,
            CustomerBulkJobModel.idempotency_key_hash == _hash(idempotency_key),
        )
    )
    if existing:
        return {"bulk_reference": existing.id, "status": existing.status}
    job = CustomerBulkJobModel(
        requested_by_admin_id=admin.id,
        operation=body.operation,
        status="READY" if body.dry_run else "COMPLETED",
        reason_code=body.reason_code,
        parameters=body.parameters,
        total_count=len(body.customer_references),
        idempotency_key_hash=_hash(idempotency_key),
    )
    db.add(job)
    db.flush()
    for ref in body.customer_references:
        status = "ELIGIBLE" if db.get(UserModel, ref) else "SKIPPED"
        db.add(
            CustomerBulkItemModel(
                job_id=job.id,
                customer_id=ref,
                status=status if body.dry_run else "COMPLETED",
                result={"dry_run": body.dry_run, "operation": body.operation},
                idempotency_key_hash=_hash(f"{job.id}:{ref}"),
            )
        )
    _audit(
        db,
        admin.id,
        "customer.bulk_created",
        "customer_bulk",
        job.id,
        request,
        {"operation": body.operation, "dry_run": body.dry_run},
    )
    return {"bulk_reference": job.id, "status": job.status, "total_count": job.total_count}


@router.get("/bulk/{job_id}")
def bulk_detail(
    job_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[AdminModel, Depends(require_perm("customers.bulk.read"))],
) -> dict[str, Any]:
    job = db.get(CustomerBulkJobModel, job_id)
    if not job:
        raise HTTPException(404)
    items = db.scalars(
        select(CustomerBulkItemModel).where(CustomerBulkItemModel.job_id == job_id)
    ).all()
    return {
        "bulk_reference": job.id,
        "status": job.status,
        "operation": job.operation,
        "items": [
            {"customer_reference": i.customer_id, "status": i.status, "result": i.result}
            for i in items
        ],
    }
