from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.customer_support_read_state import (
    MarkReadRequest,
    mark_ticket_read,
    unread_summary,
)
from platform_api.customer_support_runtime import CreateTicketRequest, create_ticket
from platform_api.identity.models import CustomerSessionModel, UserModel
from platform_api.support_notification_models import support_reply_notification_outbox
from platform_api.support_runtime_models import (
    support_conversations,
    support_idempotency_records,
    support_message_deliveries,
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


def _agent_message(
    db: Session,
    conversation_id: str,
    sequence: int,
    *,
    visibility: str = "PUBLIC",
    redacted: bool = False,
    message_type: str = "AGENT_MESSAGE",
) -> str:
    message_id = str(uuid4())
    body = f"agent-message-{sequence}"
    db.execute(
        support_messages.insert().values(
            id=message_id,
            conversation_id=conversation_id,
            sequence=sequence,
            sender_type="SUPPORT_AGENT",
            sender_id=str(uuid4()),
            channel="ADMIN_WEB",
            message_type=message_type,
            visibility=visibility,
            body=body,
            body_sha256=sha256(body.encode()).hexdigest(),
            client_idempotency_key=f"web-unread-agent-{sequence}-{uuid4().hex[:8]}",
            created_at=datetime.now(UTC),
            redacted_at=datetime.now(UTC) if redacted else None,
        )
    )
    db.commit()
    return message_id


def _cleanup(db: Session, user_ids: list[str]) -> None:
    conversation_ids = list(
        db.scalars(
            select(support_conversations.c.id).where(
                support_conversations.c.requester_user_id.in_(user_ids)
            )
        ).all()
    )
    if conversation_ids:
        message_ids = list(
            db.scalars(
                select(support_messages.c.id).where(
                    support_messages.c.conversation_id.in_(conversation_ids)
                )
            ).all()
        )
        if message_ids:
            db.execute(
                delete(support_message_deliveries).where(
                    support_message_deliveries.c.message_id.in_(message_ids)
                )
            )
            db.execute(
                delete(support_reply_notification_outbox).where(
                    support_reply_notification_outbox.c.message_id.in_(message_ids)
                )
            )
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


def test_customer_web_unread_is_owned_filtered_and_sequence_bounded() -> None:
    engine = create_engine(_postgres_url())
    settings = Settings(environment="test")
    owner_id = other_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner, owner_session, owner_csrf = _identity(db, settings)
            other, other_session, other_csrf = _identity(db, settings)
            owner_id, other_id = owner.id, other.id
            created = cast(
                dict[str, Any],
                create_ticket(
                    CreateTicketRequest(
                        subject="وضعیت خواندن پشتیبانی",
                        message="این تیکت برای تست unread ایجاد شده است.",
                    ),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    "web-unread-ticket-fixed",
                    owner_csrf,
                ),
            )
            reference = str(created["reference"])
            conversation_id = str(
                db.scalar(
                    select(support_conversations.c.id).where(
                        support_conversations.c.reference == reference
                    )
                )
            )

            first_public = _agent_message(db, conversation_id, 2)
            _agent_message(
                db,
                conversation_id,
                3,
                visibility="AGENT_ONLY",
                message_type="INTERNAL_NOTE",
            )
            second_public = _agent_message(
                db,
                conversation_id,
                4,
                message_type="AGENT_ATTACHMENT",
            )
            _agent_message(db, conversation_id, 5, redacted=True)

            owner_response = Response()
            initial = cast(dict[str, Any], unread_summary(owner_response, owner_session, db))
            assert initial == {
                "total_unread": 2,
                "tickets_with_unread": 1,
                "items": [{"reference": reference, "unread_count": 2}],
            }
            assert owner_response.headers["Cache-Control"] == "private, no-store"
            assert cast(dict[str, Any], unread_summary(Response(), other_session, db)) == {
                "total_unread": 0,
                "tickets_with_unread": 0,
                "items": [],
            }

            with pytest.raises(HTTPException) as missing_csrf:
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=2),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    None,
                )
            assert missing_csrf.value.status_code == 403

            first_read = cast(
                dict[str, Any],
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=2),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    owner_csrf,
                ),
            )
            assert first_read == {"unread_count": 1}
            deliveries = db.execute(
                select(
                    support_message_deliveries.c.message_id,
                    support_message_deliveries.c.participant_type,
                    support_message_deliveries.c.participant_id,
                    support_message_deliveries.c.read_at,
                ).where(support_message_deliveries.c.participant_id == owner.id)
            ).all()
            assert len(deliveries) == 1
            assert deliveries[0][0] == first_public
            assert deliveries[0][1] == "CUSTOMER"
            assert deliveries[0][2] == owner.id
            assert deliveries[0][3] is not None

            repeated_first = cast(
                dict[str, Any],
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=2),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    owner_csrf,
                ),
            )
            assert repeated_first == {"unread_count": 1}

            all_visible = cast(
                dict[str, Any],
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=4),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    owner_csrf,
                ),
            )
            assert all_visible == {"unread_count": 0}
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_message_deliveries)
                    .where(support_message_deliveries.c.participant_id == owner.id)
                )
                == 2
            )
            assert (
                db.scalar(
                    select(support_message_deliveries.c.read_at).where(
                        support_message_deliveries.c.message_id == second_public,
                        support_message_deliveries.c.participant_id == owner.id,
                    )
                )
                is not None
            )

            late_public = _agent_message(db, conversation_id, 6)
            assert (
                cast(dict[str, Any], unread_summary(Response(), owner_session, db))["total_unread"]
                == 1
            )

            stale_snapshot = cast(
                dict[str, Any],
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=4),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    owner_csrf,
                ),
            )
            assert stale_snapshot == {"unread_count": 1}
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(support_message_deliveries)
                    .where(
                        support_message_deliveries.c.message_id == late_public,
                        support_message_deliveries.c.participant_id == owner.id,
                    )
                )
                == 0
            )

            latest_snapshot = cast(
                dict[str, Any],
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=6),
                    Response(),
                    owner_session,
                    db,
                    settings,
                    owner_csrf,
                ),
            )
            assert latest_snapshot == {"unread_count": 0}

            with pytest.raises(HTTPException) as hidden_from_other:
                mark_ticket_read(
                    reference,
                    MarkReadRequest(through_sequence=6),
                    Response(),
                    other_session,
                    db,
                    settings,
                    other_csrf,
                )
            assert hidden_from_other.value.status_code == 404
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
