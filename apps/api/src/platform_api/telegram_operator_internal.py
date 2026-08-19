# pyright: reportPrivateUsage=false
"""Private Telegram operator bridge backed by the existing admin authority model."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .identity.models import AdminModel, TelegramAccountModel
from .management import _active_permissions
from .ops_observability import collect_operations_health
from .telegram_internal import Database, InternalAuth

router = APIRouter(
    prefix="/api/v1/internal/telegram/operator",
    tags=["internal-telegram-operator"],
    include_in_schema=False,
)

_OPERATOR_PERMISSION = "ops.telegram.read"


def operator_admin_from_telegram_subject(db: Session, telegram_id: int) -> AdminModel:
    row = db.execute(
        select(TelegramAccountModel, AdminModel)
        .join(AdminModel, AdminModel.user_id == TelegramAccountModel.user_id)
        .where(TelegramAccountModel.telegram_user_id == telegram_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator_access_denied")
    admin = row[1]
    if admin.status != "ACTIVE" or _OPERATOR_PERMISSION not in _active_permissions(db, admin.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="operator_access_denied")
    return admin


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/health")
def operator_health(
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    operator_admin_from_telegram_subject(db, x_telegram_subject)
    snapshot = collect_operations_health(db)
    _no_store(response)
    return {
        "status": snapshot.status,
        "signals": snapshot.signals,
        "worker": {
            "state": snapshot.worker.state,
            "consecutive_failures": snapshot.worker.consecutive_failures,
            "last_seen_age_seconds": snapshot.worker.last_seen_age_seconds,
        },
        "outbox": {
            "pending_due": snapshot.outbox.pending_due,
            "retrying": snapshot.outbox.retrying,
            "failed": snapshot.outbox.failed,
            "stale_claims": snapshot.outbox.stale_claims,
        },
        "fulfillment": {
            "retry_pending": snapshot.fulfillment.retry_pending,
            "blocked": snapshot.fulfillment.blocked,
            "operator_review": snapshot.fulfillment.operator_review,
            "failed": snapshot.fulfillment.failed,
        },
        "service_operations": {
            "in_progress": snapshot.service_operations.in_progress,
            "review_required": snapshot.service_operations.review_required,
        },
        "usage_sync": {
            "latest_status": snapshot.usage_sync.latest_status,
            "degraded_runs_last_hour": snapshot.usage_sync.degraded_runs_last_hour,
            "stale_active_accounts": snapshot.usage_sync.stale_active_accounts,
        },
    }
