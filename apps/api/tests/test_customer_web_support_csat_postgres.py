from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.customer_support_csat import (
    SubmitCsatRequest,
    csat_state,
    submit_csat,
)
from platform_api.customer_support_runtime import (
    CreateTicketRequest,
    ReplyTicketRequest,
    create_ticket,
    reply_ticket,
)
from platform_api.identity.models import CustomerSessionModel, UserModel
from platform_api.support_runtime_models import (
    support_conversations,
    support_csat,
    support_idempotency_records,
    support_messages,
    support_status_history,
)


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _identity(db: Session, settings: Settings) -> tuple[UserModel, CustomerSessionModel, str]:
    now = datetime.now(UTC)
    user = UserModel(id=str(uuid4()), status="ACTIVE", created_at=now, updated_at=now)
    db.add(user)
    db.flush()
    token_service = CustomerAuthService(db, settings).tokens
    csrf = token_service.generate()
    customer_session = CustomerSessionModel(
        id=str(uuid4()),
        user_id=user.id,
        refresh_token_hash=token_service.hash(token_service.generate()),
        session_family_id=str(uuid4()),
        rotation_sequence=0,
        created_at=now,
        last_used_at=now,
        idle_expires_at=now + timedelta(hours=1),
        absolute_expires_at=now + timedelta(hours=4),
        csrf_token_hash=token_service.hash(csrf),
    )
    db.add(customer_session)
    db.commit()
    return user, customer_session, csrf


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
                support_idempotency_records.c.scope == f"web-ticket:{user_id}"
            )
        )
    db.query(CustomerSessionModel).filter(CustomerSessionModel.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id.in_(user_ids)).delete(synchronize_session=False)
    db.commit()


def _create_ticket(
    db: Session,
    settings: Settings,
    customer_session: CustomerSessionModel,
    csrf: str,
    key: str,
) -> tuple[str, str]:
    ticket = cast(
        dict[str, Any],
        create_ticket(
            CreateTicketRequest(
                subject="ارزیابی پشتیبانی وب",
                message="این تیکت برای تست رضایت مشتری ایجاد شده است.",
            ),
            Response(),
            customer_session,
            db,
            settings,
            key,
            csrf,
        ),
    )
    reference = str(ticket["reference"])
    conversation_id = str(
        db.scalar(
            select(support_conversations.c.id).where(support_conversations.c.reference == reference)
        )
    )
    return reference, conversation_id


def test_customer_web_csat_is_owned_csrf_protected_and_cycles_after_reopen() -> None:
    engine = create_engine(_postgres_url())
    settings = Settings(environment="test")
    owner_id = other_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner, owner_session, owner_csrf = _identity(db, settings)
            other, other_session, _ = _identity(db, settings)
            owner_id, other_id = owner.id, other.id
            reference, conversation_id = _create_ticket(
                db, settings, owner_session, owner_csrf, "web-csat-ticket-fixed"
            )

            initial_response = Response()
            initial = cast(
                dict[str, Any], csat_state(reference, initial_response, owner_session, db)
            )
            assert initial == {"eligible": False, "submitted": False, "score": None}
            assert initial_response.headers["Cache-Control"] == "private, no-store"

            with pytest.raises(HTTPException) as missing_csrf:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback=None),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-missing-csrf",
                    None,
                )
            assert missing_csrf.value.status_code == 403

            with pytest.raises(HTTPException) as too_early:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback=None),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-too-early",
                    owner_csrf,
                )
            assert too_early.value.status_code == 409

            resolved_at = datetime.now(UTC)
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(status="RESOLVED", resolved_at=resolved_at, updated_at=resolved_at)
            )
            db.commit()
            eligible = cast(dict[str, Any], csat_state(reference, Response(), owner_session, db))
            assert eligible == {"eligible": True, "submitted": False, "score": None}

            with pytest.raises(HTTPException) as unsafe_feedback:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback="<script>alert(1)</script>"),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-unsafe",
                    owner_csrf,
                )
            assert unsafe_feedback.value.status_code == 422

            submitted = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback="پاسخ پشتیبانی دقیق و سریع بود."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-first",
                    owner_csrf,
                ),
            )
            assert submitted == {"eligible": False, "submitted": True, "score": 5}
            stored = db.execute(
                select(
                    support_csat.c.resolution_cycle,
                    support_csat.c.score,
                    support_csat.c.channel,
                ).where(support_csat.c.conversation_id == conversation_id)
            ).one()
            assert stored == (0, 5, "CUSTOMER_WEB")

            repeated = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=5, feedback="پاسخ پشتیبانی دقیق و سریع بود."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-first-retry",
                    owner_csrf,
                ),
            )
            assert repeated == submitted

            with pytest.raises(HTTPException) as changed_submission:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=4, feedback="پاسخ پشتیبانی دقیق و سریع بود."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-changed",
                    owner_csrf,
                )
            assert changed_submission.value.status_code == 409

            with pytest.raises(HTTPException) as hidden_from_other:
                csat_state(reference, Response(), other_session, db)
            assert hidden_from_other.value.status_code == 404

            reopened = cast(
                dict[str, Any],
                reply_ticket(
                    reference,
                    ReplyTicketRequest(message="مشکل دوباره برگشته و تیکت را باز می‌کنم."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-reopen",
                    owner_csrf,
                ),
            )
            assert reopened["status"] == "WAITING_FOR_SUPPORT"
            during_reopen = cast(
                dict[str, Any], csat_state(reference, Response(), owner_session, db)
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
                dict[str, Any], csat_state(reference, Response(), owner_session, db)
            )
            assert second_cycle == {"eligible": True, "submitted": False, "score": None}

            second_submission = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=4, feedback=None),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-second-cycle",
                    owner_csrf,
                ),
            )
            assert second_submission == {"eligible": False, "submitted": True, "score": 4}
            cycles = db.execute(
                select(
                    support_csat.c.resolution_cycle,
                    support_csat.c.score,
                    support_csat.c.channel,
                )
                .where(support_csat.c.conversation_id == conversation_id)
                .order_by(support_csat.c.resolution_cycle)
            ).all()
            assert cycles == [(0, 5, "CUSTOMER_WEB"), (1, 4, "CUSTOMER_WEB")]
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()


def test_customer_web_csat_respects_existing_cross_channel_submission() -> None:
    engine = create_engine(_postgres_url())
    settings = Settings(environment="test")
    owner_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner, owner_session, owner_csrf = _identity(db, settings)
            owner_id = owner.id
            reference, conversation_id = _create_ticket(
                db, settings, owner_session, owner_csrf, "web-csat-cross-channel-ticket"
            )
            resolved_at = datetime.now(UTC)
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(status="RESOLVED", resolved_at=resolved_at, updated_at=resolved_at)
            )
            db.execute(
                support_csat.insert().values(
                    id=str(uuid4()),
                    conversation_id=conversation_id,
                    resolution_cycle=0,
                    score=3,
                    feedback="از کانال دیگر ثبت شده است.",
                    channel="TELEGRAM_BOT",
                    submitted_at=resolved_at,
                )
            )
            db.commit()

            state = cast(dict[str, Any], csat_state(reference, Response(), owner_session, db))
            assert state == {"eligible": False, "submitted": True, "score": 3}

            repeated = cast(
                dict[str, Any],
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=3, feedback="از کانال دیگر ثبت شده است."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-cross-channel-retry",
                    owner_csrf,
                ),
            )
            assert repeated == state

            with pytest.raises(HTTPException) as changed_cross_channel:
                submit_csat(
                    reference,
                    SubmitCsatRequest(score=4, feedback="از کانال دیگر ثبت شده است."),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-csat-cross-channel-changed",
                    owner_csrf,
                )
            assert changed_cross_channel.value.status_code == 409
        finally:
            if owner_id:
                _cleanup(db, [owner_id])
    engine.dispose()
