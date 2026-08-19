from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session, sessionmaker

import platform_api.telegram_operator_internal as operator_module
from platform_api.identity.models import (
    AdminModel,
    IdentityBase,
    TelegramAccountModel,
    UserModel,
)
from platform_api.telegram_operator_internal import operator_admin_from_telegram_subject


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    IdentityBase.metadata.create_all(
        engine,
        tables=[
            cast(Table, UserModel.__table__),
            cast(Table, TelegramAccountModel.__table__),
            cast(Table, AdminModel.__table__),
        ],
    )
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _seed(factory: sessionmaker[Session], *, admin_status: str = "ACTIVE") -> tuple[int, str]:
    telegram_id = 424242
    now = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)
    placeholder_hash = "".join(("$argon2id$", "test-only"))
    with factory.begin() as db:
        user = UserModel(status="ACTIVE")
        db.add(user)
        db.flush()
        admin = AdminModel(
            user_id=user.id,
            normalized_email="operator@example.test",
            password_hash=placeholder_hash,
            status=admin_status,
            failed_login_count=0,
        )
        db.add(admin)
        db.flush()
        db.add(
            TelegramAccountModel(
                telegram_user_id=telegram_id,
                user_id=user.id,
                first_seen_at=now,
                last_seen_at=now,
                bot_started=True,
                blocked_bot=False,
            )
        )
        admin_id = admin.id
    return telegram_id, admin_id


def _allowed_permissions(_db: Session, _admin_id: str) -> set[str]:
    return {"ops.telegram.read"}


def _no_permissions(_db: Session, _admin_id: str) -> set[str]:
    return set()


def test_operator_authority_requires_same_linked_active_admin_and_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    telegram_id, admin_id = _seed(factory)
    monkeypatch.setattr(operator_module, "_active_permissions", _allowed_permissions)

    with factory() as db:
        assert operator_admin_from_telegram_subject(db, telegram_id).id == admin_id
        with pytest.raises(HTTPException) as missing:
            operator_admin_from_telegram_subject(db, telegram_id + 1)
    assert missing.value.status_code == 403
    assert missing.value.detail == "operator_access_denied"


def test_operator_authority_fails_closed_for_inactive_or_unpermitted_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inactive_factory = _factory()
    inactive_id, _ = _seed(inactive_factory, admin_status="DISABLED")
    monkeypatch.setattr(operator_module, "_active_permissions", _allowed_permissions)
    with inactive_factory() as db, pytest.raises(HTTPException) as inactive:
        operator_admin_from_telegram_subject(db, inactive_id)
    assert inactive.value.detail == "operator_access_denied"

    unpermitted_factory = _factory()
    unpermitted_id, _ = _seed(unpermitted_factory)
    monkeypatch.setattr(operator_module, "_active_permissions", _no_permissions)
    with unpermitted_factory() as db, pytest.raises(HTTPException) as unpermitted:
        operator_admin_from_telegram_subject(db, unpermitted_id)
    assert unpermitted.value.status_code == 403
    assert unpermitted.value.detail == "operator_access_denied"
