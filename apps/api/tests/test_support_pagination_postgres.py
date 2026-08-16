from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.identity.models import TelegramAccountModel, UserModel
from platform_api.support_pagination_runtime import (
    _decode_cursor,
    _encode_cursor,
    telegram_ticket_detail_page,
    telegram_ticket_page,
)
from platform_api.support_runtime_models import (
    support_conversations,
    support_idempotency_records,
    support_messages,
    support_status_history,
)
from platform_api.telegram_support_internal import CreateTicketRequest, create_ticket


def _postgres_url() -> str:
    value = os.environ.get("VPN_SALE_DATABASE_URL", "")
    if not value.startswith("postgresql"):
        pytest.skip("PostgreSQL integration URL is unavailable")
    return value.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)


def _settings() -> Settings:
    return Settings(
        environment="test",
        customer_access_token_signing_key=sha256(b"support-pagination-settings-fixture").hexdigest(),
    )


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


def test_cursor_is_signed_and_bound_to_its_read_surface() -> None:
    secret = sha256(b"support-pagination-cursor-contract").hexdigest()
    cursor = _encode_cursor(secret, "tickets", {"s": 42})
    assert _decode_cursor(secret, "tickets", cursor) == {"s": 42}

    encoded, signature = cursor.split(".", 1)
    tampered_signature = "A" if signature[-1] != "A" else "B"
    tampered = f"{encoded}.{signature[:-1]}{tampered_signature}"
    with pytest.raises(ValueError, match="invalid cursor"):
        _decode_cursor(secret, "tickets", tampered)
    with pytest.raises(ValueError, match="cursor"):
        _decode_cursor(secret, "messages", cursor)


def test_telegram_support_ticket_and_message_pages_are_complete_owned_and_deduplicated() -> None:
    engine = create_engine(_postgres_url())
    owner_id = other_id = ""
    with Session(engine, expire_on_commit=False) as db:
        try:
            owner_id, owner_telegram = _identity(db)
            other_id, other_telegram = _identity(db)
            references: list[str] = []
            for index in range(12):
                created = cast(
                    dict[str, Any],
                    create_ticket(
                        CreateTicketRequest(
                            subject=f"Pagination ticket {index:02d}",
                            message=f"initial-{index}",
                        ),
                        Response(),
                        None,
                        db,
                        owner_telegram,
                        f"support-page-create-{index:02d}",
                    ),
                )
                references.append(str(created["reference"]))

            seen_references: list[str] = []
            cursor: str | None = None
            response_cursors: list[str] = []
            while True:
                page = cast(
                    dict[str, Any],
                    telegram_ticket_page(
                        Response(),
                        None,
                        db,
                        owner_telegram,
                        _settings(),
                        limit=5,
                        cursor=cursor,
                    ),
                )
                items = cast(list[dict[str, Any]], page["items"])
                seen_references.extend(str(item["reference"]) for item in items)
                next_cursor = page["next_cursor"]
                if next_cursor is None:
                    break
                assert isinstance(next_cursor, str)
                response_cursors.append(next_cursor)
                cursor = next_cursor

            assert len(seen_references) == 12
            assert len(set(seen_references)) == 12
            assert set(seen_references) == set(references)
            assert all(owner_id not in value for value in response_cursors)

            reference = references[0]
            conversation_id = str(
                db.scalar(
                    select(support_conversations.c.id).where(
                        support_conversations.c.reference == reference
                    )
                )
            )
            now = datetime.now(UTC)
            for sequence in range(2, 27):
                body = f"customer-history-{sequence}"
                db.execute(
                    support_messages.insert().values(
                        id=str(uuid4()),
                        conversation_id=conversation_id,
                        sequence=sequence,
                        sender_type="CUSTOMER",
                        sender_id=owner_id,
                        channel="TELEGRAM_BOT",
                        message_type="CUSTOMER_MESSAGE",
                        visibility="PUBLIC",
                        body=body,
                        body_sha256=sha256(body.encode()).hexdigest(),
                        client_idempotency_key=f"pagination-message-{sequence}",
                        created_at=now,
                    )
                )
            db.commit()

            seen_sequences: list[int] = []
            cursor = None
            first_cursor: str | None = None
            while True:
                detail = cast(
                    dict[str, Any],
                    telegram_ticket_detail_page(
                        reference,
                        Response(),
                        None,
                        db,
                        owner_telegram,
                        _settings(),
                        limit=10,
                        cursor=cursor,
                    ),
                )
                messages = cast(list[dict[str, Any]], detail["messages"])
                page_sequences = [int(message["sequence"]) for message in messages]
                assert page_sequences == sorted(page_sequences)
                seen_sequences.extend(page_sequences)
                next_cursor = detail["messages_next_cursor"]
                if first_cursor is None and isinstance(next_cursor, str):
                    first_cursor = next_cursor
                if next_cursor is None:
                    break
                assert isinstance(next_cursor, str)
                assert conversation_id not in next_cursor
                assert owner_id not in next_cursor
                cursor = next_cursor

            assert len(seen_sequences) == 26
            assert len(set(seen_sequences)) == 26
            assert set(seen_sequences) == set(range(1, 27))
            assert first_cursor is not None

            with pytest.raises(HTTPException) as ownership_error:
                telegram_ticket_detail_page(
                    reference,
                    Response(),
                    None,
                    db,
                    other_telegram,
                    _settings(),
                    limit=10,
                    cursor=first_cursor,
                )
            assert ownership_error.value.status_code == 404

            tampered = f"{first_cursor[:-1]}{'A' if first_cursor[-1] != 'A' else 'B'}"
            with pytest.raises(HTTPException) as cursor_error:
                telegram_ticket_detail_page(
                    reference,
                    Response(),
                    None,
                    db,
                    owner_telegram,
                    _settings(),
                    limit=10,
                    cursor=tampered,
                )
            assert cursor_error.value.status_code == 400
            assert cursor_error.value.detail == "support_cursor_invalid"
        finally:
            if owner_id or other_id:
                _cleanup(db, [value for value in (owner_id, other_id) if value])
    engine.dispose()
