from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import Response
from sqlalchemy import create_engine, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from platform_api.identity.models import TelegramAccountModel, UserModel
from platform_api.support_notification_models import support_reply_notification_outbox
from platform_api.support_runtime_models import (
    support_conversations,
    support_idempotency_records,
    support_messages,
)
from platform_api.support_sla_models import support_notifications, support_sla_escalations
from platform_api.telegram_support_internal import CreateTicketRequest, create_ticket
from platform_worker.support_sla_escalation import SupportSlaEscalationWorker, _phase


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


def _cleanup(db: Session, user_id: str, conversation_id: str) -> None:
    db.execute(
        delete(support_notifications).where(
            support_notifications.c.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(support_sla_escalations).where(
            support_sla_escalations.c.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(support_reply_notification_outbox).where(
            support_reply_notification_outbox.c.conversation_id == conversation_id
        )
    )
    db.execute(
        delete(support_messages).where(support_messages.c.conversation_id == conversation_id)
    )
    db.execute(delete(support_conversations).where(support_conversations.c.id == conversation_id))
    db.execute(
        delete(support_idempotency_records).where(
            support_idempotency_records.c.scope == f"tg-ticket:{user_id}"
        )
    )
    db.query(TelegramAccountModel).filter(TelegramAccountModel.user_id == user_id).delete(
        synchronize_session=False
    )
    db.query(UserModel).filter(UserModel.id == user_id).delete(synchronize_session=False)
    db.commit()


def test_at_risk_window_is_bounded_and_breach_wins() -> None:
    now = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
    assert _phase(now, now - timedelta(seconds=1), 240) == "BREACHED"
    assert _phase(now, now + timedelta(minutes=40), 240) == "AT_RISK"
    assert _phase(now, now + timedelta(minutes=70), 240) is None


def test_worker_deduplicates_response_debts_and_pauses_customer_wait() -> None:
    engine = create_engine(_postgres_url())
    factory = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    user_id = conversation_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            user_id, telegram_id = _identity(db)
            created = create_ticket(
                CreateTicketRequest(
                    subject="SLA worker fixture",
                    message="Customer message that must never enter escalation payloads.",
                ),
                Response(),
                None,
                db,
                telegram_id,
                "sla-worker-create-fixed",
            )
            reference = str(created["reference"])
            row = (
                db.execute(
                    select(support_conversations).where(
                        support_conversations.c.reference == reference
                    )
                )
                .mappings()
                .one()
            )
            conversation_id = str(row["id"])
            now = datetime.now(UTC)
            db.execute(
                update(support_messages)
                .where(
                    support_messages.c.conversation_id == conversation_id,
                    support_messages.c.sequence == 1,
                )
                .values(created_at=now - timedelta(minutes=40))
            )
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(first_response_deadline=now - timedelta(minutes=1))
            )
            db.commit()

            worker = SupportSlaEscalationWorker(factory)
            assert worker.run_once(now) == 1
            assert worker.run_once(now) == 0

            escalation = (
                db.execute(
                    select(support_sla_escalations).where(
                        support_sla_escalations.c.conversation_id == conversation_id
                    )
                )
                .mappings()
                .one()
            )
            assert escalation["kind"] == "FIRST_RESPONSE"
            assert escalation["phase"] == "BREACHED"
            notification = (
                db.execute(
                    select(support_notifications).where(
                        support_notifications.c.conversation_id == conversation_id
                    )
                )
                .mappings()
                .one()
            )
            payload = notification["safe_payload"]
            assert payload["ticket_reference"] == reference
            assert "message" not in repr(payload).lower()
            assert "customer" not in repr(payload).lower()
            assert "SLA worker fixture" not in repr(payload)

            snapshot = dict(row["sla_policy_snapshot"])
            snapshot["next_response_minutes"] = 5
            agent_body = "Public support answer"
            customer_body = "Customer replied again"
            db.execute(
                support_messages.insert().values(
                    id=str(uuid4()),
                    conversation_id=conversation_id,
                    sequence=2,
                    sender_type="SUPPORT_AGENT",
                    sender_id=str(uuid4()),
                    channel="ADMIN_WEB",
                    message_type="AGENT_MESSAGE",
                    visibility="PUBLIC",
                    body=agent_body,
                    body_sha256=sha256(agent_body.encode()).hexdigest(),
                    client_idempotency_key="sla-agent-message",
                    created_at=now - timedelta(minutes=30),
                )
            )
            db.execute(
                support_messages.insert().values(
                    id=str(uuid4()),
                    conversation_id=conversation_id,
                    sequence=3,
                    sender_type="CUSTOMER",
                    sender_id=user_id,
                    channel="TELEGRAM_BOT",
                    message_type="CUSTOMER_MESSAGE",
                    visibility="PUBLIC",
                    body=customer_body,
                    body_sha256=sha256(customer_body.encode()).hexdigest(),
                    client_idempotency_key="sla-customer-message",
                    created_at=now - timedelta(minutes=10),
                )
            )
            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(sla_policy_snapshot=snapshot)
            )
            db.commit()
            assert worker.run_once(now) == 1
            kinds = set(
                db.scalars(
                    select(support_sla_escalations.c.kind).where(
                        support_sla_escalations.c.conversation_id == conversation_id
                    )
                ).all()
            )
            assert kinds == {"FIRST_RESPONSE", "NEXT_RESPONSE"}

            db.execute(
                update(support_conversations)
                .where(support_conversations.c.id == conversation_id)
                .values(
                    status="WAITING_FOR_CUSTOMER",
                    resolution_deadline=now - timedelta(minutes=1),
                )
            )
            db.commit()
            assert worker.run_once(now) == 0
        finally:
            if user_id and conversation_id:
                _cleanup(db, user_id, conversation_id)
    engine.dispose()
