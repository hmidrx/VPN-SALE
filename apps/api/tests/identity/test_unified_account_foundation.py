from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.identity import (
    AccountCredential,
    AccountEmail,
    AccountUsername,
    normalize_account_username,
    validate_telegram_ownership,
)

from platform_api.identity.models import (
    AccountCredentialModel,
    AccountEmailModel,
    AdminModel,
    IdentityBase,
    TelegramAccountModel,
    UserModel,
)


def runtime_hash(label: str) -> str:
    return "$" + "argon2id$" + label


def test_account_domain_invariants() -> None:
    assert normalize_account_username("Ali.Test") == "ali.test"
    for invalid in ("abc", "has space", "نام", "a" * 33):
        with pytest.raises(ValueError):
            AccountUsername(invalid)
    user_id = uuid4()
    credential = AccountCredential(
        user_id, AccountUsername("Ali.Test"), runtime_hash("runtime"), datetime.now(UTC)
    )
    assert credential.credential_version == 1
    with pytest.raises(ValueError):
        AccountCredential(user_id, AccountUsername("valid_name"), "plaintext", datetime.now(UTC))
    assert not AccountEmail(user_id, "Person@Example.COM").recovery_eligible
    validate_telegram_ownership(None, user_id)
    with pytest.raises(ValueError):
        validate_telegram_ownership(uuid4(), user_id)


def test_database_one_to_one_and_canonical_uniqueness() -> None:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    now = datetime.now(UTC)
    with Session(engine) as session:
        users = [UserModel(status="ACTIVE") for _ in range(3)]
        session.add_all(users)
        session.commit()
        session.add_all(
            [
                AccountCredentialModel(
                    user_id=users[0].id,
                    username="Ali.Test",
                    normalized_username="ali.test",
                    password_hash=runtime_hash("one"),
                    password_changed_at=now,
                ),
                AccountCredentialModel(
                    user_id=users[1].id,
                    username="ali.test",
                    normalized_username="ali.test",
                    password_hash=runtime_hash("two"),
                    password_changed_at=now,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        users = session.query(UserModel).all()
        session.add_all(
            [
                TelegramAccountModel(
                    telegram_user_id=11, user_id=users[0].id, first_seen_at=now, last_seen_at=now
                ),
                TelegramAccountModel(
                    telegram_user_id=12, user_id=users[0].id, first_seen_at=now, last_seen_at=now
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        session.add_all(
            [
                TelegramAccountModel(
                    telegram_user_id=21, user_id=None, first_seen_at=now, last_seen_at=now
                ),
                TelegramAccountModel(
                    telegram_user_id=22, user_id=None, first_seen_at=now, last_seen_at=now
                ),
            ]
        )
        session.commit()
        assert session.query(TelegramAccountModel).count() == 2


def test_email_and_admin_link_are_unique() -> None:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    with Session(engine) as session:
        users = [UserModel(status="ACTIVE") for _ in range(2)]
        session.add_all(users)
        session.commit()
        session.add_all(
            [
                AccountEmailModel(user_id=users[0].id, normalized_email="a@example.test"),
                AccountEmailModel(user_id=users[1].id, normalized_email="a@example.test"),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        users = session.query(UserModel).all()
        session.add_all(
            [
                AdminModel(
                    user_id=users[0].id,
                    normalized_email="one@example.test",
                    password_hash=runtime_hash("one"),
                    status="ACTIVE",
                ),
                AdminModel(
                    user_id=users[0].id,
                    normalized_email="two@example.test",
                    password_hash=runtime_hash("two"),
                    status="ACTIVE",
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.flush()
