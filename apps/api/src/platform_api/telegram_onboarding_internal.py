"""Service-authenticated Telegram onboarding for the production bot runtime."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .identity.models import (
    AuditLogModel,
    CustomerProfileModel,
    RoleModel,
    TelegramAccountModel,
    UserModel,
    UserRoleAssignmentModel,
)
from .telegram_internal import Database, InternalAuth

router = APIRouter(
    prefix="/api/v1/internal/telegram",
    tags=["internal-telegram-onboarding"],
    include_in_schema=False,
)

_ALLOWED_ACCOUNT_STATES = {"ACTIVE", "PENDING"}


class TrustedResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_user_id: int = Field(gt=0)
    username: str | None = Field(default=None, max_length=32)
    first_name: str | None = Field(default=None, max_length=128)
    last_name: str | None = Field(default=None, max_length=128)
    language_code: str | None = Field(default=None, max_length=16)
    bot_started: bool = True


def _load_owned_account(
    db: Session, telegram_user_id: int, *, lock: bool
) -> tuple[TelegramAccountModel, UserModel] | None:
    statement = select(TelegramAccountModel).where(
        TelegramAccountModel.telegram_user_id == telegram_user_id
    )
    if lock:
        statement = statement.with_for_update()
    account = db.scalar(statement)
    if account is None or account.user_id is None:
        return None
    user = db.get(UserModel, account.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="identity_inconsistent",
        )
    return account, user


def _customer_role(db: Session) -> RoleModel:
    role = db.scalar(select(RoleModel).where(RoleModel.machine_name == "customer"))
    if role is None or not role.active:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity_onboarding_unavailable",
        )
    return role


def _audit_created(
    db: Session, user: UserModel, account: TelegramAccountModel, now: datetime
) -> None:
    db.add_all(
        [
            AuditLogModel(
                actor_type="customer",
                actor_id=user.id,
                target_type="customer",
                target_id=user.id,
                event_code="customer.registered",
                occurred_at=now,
                metadata_={"method": "telegram_bot"},
            ),
            AuditLogModel(
                actor_type="customer",
                actor_id=user.id,
                target_type="telegram_identity",
                target_id=account.id,
                event_code="customer.telegram_identity.created",
                occurred_at=now,
                metadata_={"method": "telegram_bot"},
            ),
        ]
    )


def _create_or_claim_account(
    db: Session, body: TrustedResolveRequest, now: datetime
) -> tuple[TelegramAccountModel, UserModel, bool]:
    resolved = _load_owned_account(db, body.telegram_user_id, lock=True)
    if resolved is not None:
        return resolved[0], resolved[1], False

    try:
        with db.begin_nested():
            # Recheck under a savepoint so an unowned row and a concurrent first-start are both
            # serialized by the database rather than by Telegram delivery timing.
            resolved = _load_owned_account(db, body.telegram_user_id, lock=True)
            if resolved is not None:
                return resolved[0], resolved[1], False

            account = db.scalar(
                select(TelegramAccountModel)
                .where(TelegramAccountModel.telegram_user_id == body.telegram_user_id)
                .with_for_update()
            )
            user = UserModel(status="PENDING", created_at=now, updated_at=now)
            db.add(user)
            db.flush()
            db.add(
                CustomerProfileModel(
                    user_id=user.id,
                    display_name=body.first_name,
                    locale=body.language_code or "fa",
                )
            )
            if account is None:
                account = TelegramAccountModel(
                    telegram_user_id=body.telegram_user_id,
                    user_id=user.id,
                    first_seen_at=now,
                    last_seen_at=now,
                    bot_started=body.bot_started,
                    blocked_bot=False,
                )
                db.add(account)
            else:
                account.user_id = user.id
            role = _customer_role(db)
            db.add(
                UserRoleAssignmentModel(
                    user_id=user.id,
                    role_id=role.id,
                    assigned_at=now,
                )
            )
            db.flush()
            _audit_created(db, user, account, now)
            db.flush()
            return account, user, True
    except IntegrityError:
        # A competing request may have won the unique telegram_user_id insert. The savepoint
        # rollback keeps this request usable; fetch and lock the durable winner.
        resolved = _load_owned_account(db, body.telegram_user_id, lock=True)
        if resolved is None:
            raise
        return resolved[0], resolved[1], False


def _customer_reference(settings: Settings, user_id: str) -> str:
    try:
        key = Path(settings.telegram_internal_token_file).read_bytes().strip()
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity_reference_unavailable",
        ) from exc
    if len(key) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity_reference_unavailable",
        )
    return hmac.new(key, user_id.encode(), hashlib.sha256).hexdigest()[:24]


@router.post("/identity/register-or-resolve")
def register_or_resolve(
    body: TrustedResolveRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    if x_telegram_subject != body.telegram_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="subject_mismatch")

    now = datetime.now(UTC)
    account, user, created = _create_or_claim_account(db, body, now)
    if user.status in _ALLOWED_ACCOUNT_STATES:
        account.username = body.username
        account.first_name = body.first_name
        account.last_name = body.last_name
        account.language_code = body.language_code
        account.bot_started = body.bot_started
        account.blocked_bot = False
        account.last_seen_at = now
        profile = db.get(CustomerProfileModel, user.id)
        if profile is not None:
            if body.first_name and not profile.display_name:
                profile.display_name = body.first_name
            if body.language_code:
                profile.locale = body.language_code
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    profile = db.get(CustomerProfileModel, user.id)
    return {
        "customer_reference": _customer_reference(settings, user.id),
        "account_state": user.status,
        "created": created,
        "locale": (profile.locale if profile and profile.locale else body.language_code) or "fa",
    }
