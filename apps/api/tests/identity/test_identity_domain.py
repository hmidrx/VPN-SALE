from __future__ import annotations

from uuid import uuid4

import pytest
from vpnsale_domain.identity import (
    Admin,
    AdminStatus,
    AuditLog,
    InvalidStatusTransition,
    Permission,
    SensitiveMetadataError,
    TelegramAccount,
    User,
    UserStatus,
    normalize_email,
)

TEST_PASSWORD_HASH = "$argon2id$test"  # noqa: S105


def test_user_status_transitions_are_explicit() -> None:
    user = User(id=uuid4())
    assert user.transition_to(UserStatus.ACTIVE).status is UserStatus.ACTIVE
    with pytest.raises(InvalidStatusTransition):
        user.transition_to(UserStatus.BLOCKED)


def test_admin_status_transitions_are_explicit() -> None:
    admin = Admin(id=uuid4(), email="Admin@Example.COM ", password_hash=TEST_PASSWORD_HASH)
    assert admin.email == "admin@example.com"
    assert (
        admin.transition_to(AdminStatus.ACTIVE)
        .transition_to(AdminStatus.LOCKED)
        .transition_to(AdminStatus.ACTIVE)
        .status
        is AdminStatus.ACTIVE
    )
    with pytest.raises(InvalidStatusTransition):
        admin.transition_to(AdminStatus.LOCKED)


def test_email_and_telegram_normalization() -> None:
    assert normalize_email(" SUPPORT@Example.COM ") == "support@example.com"
    account = TelegramAccount(
        telegram_user_id=123,
        username="@Mixed",
        first_name="  Ada   Lovelace  ",
        start_attribution=" campaign ",
    )
    assert account.username == "mixed"
    assert account.first_name == "Ada Lovelace"
    assert account.start_attribution == "campaign"


def test_permission_code_validation() -> None:
    assert Permission(code="admins.read", description="Read admins").code == "admins.read"
    with pytest.raises(ValueError):
        Permission(code="Admins Read", description="bad")


def test_audit_metadata_rejects_secret_looking_fields() -> None:
    with pytest.raises(SensitiveMetadataError):
        AuditLog(
            id=uuid4(),
            actor_type="admin",
            actor_id="a",
            target_type="admin",
            target_id="b",
            event_code="admin.login.failed",
            occurred_at=User(id=uuid4()).created_at,
            metadata={"refresh_token": "abc"},
        )
