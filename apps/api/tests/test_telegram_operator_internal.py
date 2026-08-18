from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import platform_api.telegram_operator_internal as operator_module
from platform_api.identity.models import AdminModel, TelegramAccountModel, UserModel
from platform_api.telegram_operator_internal import _operator_admin


def _factory() -> sessionmaker[Session]:
    engine = create_engine("sqlite://")
    UserModel.__table__.create(engine)
    TelegramAccountModel.__table__.create(engine)
    AdminModel.__table__.create(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def _seed(factory: sessionmaker[Session], *, admin_status: str = "ACTIVE") -> tuple[int, str]:
    telegram_id = 424242
    now = datetime(2026, 8, 18, 14, 0, tzinfo=UTC)
    with factory.begin() as db:
        user = UserModel(status="ACTIVE")
        db.add(user)
        db.flush()
        admin = AdminModel(
            user_id=user.id,
            normalized_email="operator@example.test",
            password_hash="$argon2id$test-only",
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


def test_operator_authority_requires_same_linked_active_admin_and_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    telegram_id, admin_id = _seed(factory)
    monkeypatch.setattr(
        operator_module,
        "_active_permissions",
        lambda _db, _admin_id: {"ops.telegram.read"},
    )

    with factory() as db:
        assert _operator_admin(db, telegram_id).id == admin_id
        with pytest.raises(HTTPException) as missing:
            _operator_admin(db, telegram_id + 1)
    assert missing.value.status_code == 403
    assert missing.value.detail == "operator_access_denied"


def test_operator_authority_fails_closed_for_inactive_or_unpermitted_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inactive_factory = _factory()
    inactive_id, _ = _seed(inactive_factory, admin_status="DISABLED")
    monkeypatch.setattr(
        operator_module,
        "_active_permissions",
        lambda _db, _admin_id: {"ops.telegram.read"},
    )
    with inactive_factory() as db, pytest.raises(HTTPException) as inactive:
        _operator_admin(db, inactive_id)
    assert inactive.value.detail == "operator_access_denied"

    unpermitted_factory = _factory()
    unpermitted_id, _ = _seed(unpermitted_factory)
    monkeypatch.setattr(operator_module, "_active_permissions", lambda _db, _admin_id: set())
    with unpermitted_factory() as db, pytest.raises(HTTPException) as unpermitted:
        _operator_admin(db, unpermitted_id)
    assert unpermitted.value.status_code == 403
    assert unpermitted.value.detail == "operator_access_denied"
