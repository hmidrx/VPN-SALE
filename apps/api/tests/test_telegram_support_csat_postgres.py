from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from platform_api.identity.models import TelegramAccountModel, UserModel
from platform_api.support_runtime_models import (
    support_conversations,
    support_csat,
    support_idempotency_records,
    support_messages,
    support_status_history,
)
from platform_api.telegram_support_csat_internal import (
    SubmitCsatRequest,
    csat_state,
    submit_csat,
)
from platform_api.telegram_support_internal import (
    CreateTicketRequest,
    ReplyTicketRequest,
    create_ticket,
    reply_ticket,
)


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _identity(db: Session) -> tuple[str, int]:
    user_id = str(uuid4())
    telegram_id = int(uuid4().hex[:12], 16)
    now = datetime.now(UTC)
    db.add(UserModel(id=user_id, status="ACTIVE"))
    db.flush()
    db.add(
        TelegramAccountModel(
            telegram_user_id=telegram_id,
            user_id=user_id,
            first_seen_at=now,
            last_seen_at=now,
            bot_started=True,
            blocked_bot=False,
        )
    )
    db.commit()
    return user_id, telegram_id


def _cleanup(db: Session, user_ids: list[str]) -> None:
    conversation_ids = list(
        db.scalars(
            select(support_conversations.c.id).where(
                support_conversations.c.requester_user_id.in_(user_ids)
            )
        ).all()
    )
    if conversation_ids:
        db.execute(delete(support_csat).where(support_csat.c.conversation_id.in_(conversation_ids)))
        db.execute(
            delete(support_status_history).where(
                support_status_history.c.conversation_id.in_(conversation_ids)
            )
        )
        db.execute(
            delete(support_messages).where(support_messages.c.conversation_id.in_(conversation_ids))
        )
        db.execute(
            delete(support_conversations).where(support_conversations.c.id.in_(conversation_ids))
        )
    for user_id in user_ids:
        db.execute(
            delete(support_idempotency_records).where(
                support_idempotency_records.c.scope == f"tg-ticket:{user_id}"
            )
        )
    db.query(TelegramAccountModel).filter(TelegramAccountModel.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()


def test_native_support_csat_is_owned_idempotent_and_cycles_after_reopen() -> None:
    engine = create_engine(_postgres_url())
    owner_id = other_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner_id, owner_telegram = _identity(db)
            other_id, other_telegram = _identity(db)
            ticket = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(
                        subject="بررسی کیفیت پشتیبانی",
                        message="برای تست چرخه رضایت ایجاد شده است.",
                    ),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-create-fixed",
                ),
            )
            reference = str(ticket["reference"])
            conversation_id = str(
                db.scalar(
                    select(support_conversations.c.id).where(
                        support_conversations.c.reference == reference
                    )
                )
            )

            initial_response = Response()
            initial = cast(
                dict[str, Any],
                csat_state(reference, initial_response, None, db, owner_telegram),
            )
            assert initial == {"eligible": False, "submitted": False, "score": None}
            assert initial_response.headers["Cache-Control"] == "private, no-store"

            with pytest.raises(HTTPException) as not_eligible:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback=None),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-too-early",
                )
            assert not_eligible.value.status_code == 409

            now = datetime.now(UTC)
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(status="RESOLVED", resolved_at=now, updated_at=now)
            )
            db.commit()
            eligible = cast(
                dict[str, Any], csat_state(reference, Response(), None, db, owner_telegram)
            )
            assert eligible == {"eligible": True, "submitted": False, "score": None}

            with pytest.raises(HTTPException) as unsafe_feedback:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback="<script>alert(1)</script>"),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-unsafe",
                )
            assert unsafe_feedback.value.status_code == 422

            submitted = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback="پاسخ سریع و دقیق بود."),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-first",
                ),
            )
            assert submitted == {"eligible": False, "submitted": True, "score": 5}

            repeated = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback="پاسخ سریع و دقیق بود."),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-first-retry",
                ),
            )
            assert repeated == submitted

            with pytest.raises(HTTPException) as duplicate_changed:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=4, feedback="پاسخ سریع و دقیق بود."),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-changed",
                )
            assert duplicate_changed.value.status_code == 409

            with pytest.raises(HTTPException) as hidden_from_other_customer:
                csat_state(reference, Response(), None, db, other_telegram)
            assert hidden_from_other_customer.value.status_code == 404

            reopened = cast(
                dict[str, Any],
                reply_ticket(
                    reference,
                    ReplyTicketRequest(message="مشکل دوباره برگشته و تیکت باز شد."),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-reopen",
                ),
            )
            assert reopened["status"] == "WAITING_FOR_SUPPORT"
            during_reopen = cast(
                dict[str, Any], csat_state(reference, Response(), None, db, owner_telegram)
            )
            assert during_reopen == {"eligible": False, "submitted": False, "score": None}

            second_resolved_at = datetime.now(UTC)
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(
                    status="RESOLVED",
                    resolved_at=second_resolved_at,
                    updated_at=second_resolved_at,
                )
            )
            db.commit()
            second_cycle = cast(
                dict[str, Any], csat_state(reference, Response(), None, db, owner_telegram)
            )
            assert second_cycle == {"eligible": True, "submitted": False, "score": None}

            second_submission = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=4, feedback=None),
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    "tg-csat-second-cycle",
                ),
            )
            assert second_submission == {"eligible": False, "submitted": True, "score": 4}
            stored_cycles = db.execute(
                select(support_csat.c.resolution_cycle, support_csat.c.score)
                .where(support_csat.c.conversation_id == conversation_id)
                .order_by(support_csat.c.resolution_cycle)
            ).all()
            assert stored_cycles == [(0, 5), (1, 4)]
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
