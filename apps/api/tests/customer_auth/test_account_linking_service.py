from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.customer_auth.models import TelegramLinkChallengeModel
from platform_api.customer_auth.service import AccountLinkConflict, CustomerAuthService
from platform_api.customer_auth.telegram import TelegramInitData, TelegramUser
from platform_api.identity.models import (
    AccountCredentialModel,
    CustomerSessionModel,
    IdentityBase,
    SecurityEventModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.identity.rbac_seed import seed_initial_rbac

NOW = datetime(2026, 7, 26, tzinfo=UTC)
PASSWORD = "correct horse account linking passphrase"  # noqa: S105


class FakeVerifier:
    def __init__(self, telegram_id: int, start_param: str | None = None) -> None:
        self.telegram_id = telegram_id
        self.start_param = start_param

    def verify(self, raw: str, *, now: datetime) -> TelegramInitData:
        if raw != "signed-init-data":
            raise ValueError("invalid")
        return TelegramInitData(
            TelegramUser(self.telegram_id, "presentation", "Customer", None, "fa", None),
            now,
            self.start_param,
        )


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    session = Session(engine)
    seed_initial_rbac(session)
    session.commit()
    return session


def _service(db: Session) -> CustomerAuthService:
    return CustomerAuthService(db, Settings(telegram_bot_token=_test_bot_token()))


def _test_bot_token() -> str:
    return "-".join(("test", "token"))


def _password_account(db: Session) -> tuple[CustomerAuthService, str, str]:
    service = _service(db)
    result = service.register_password_account("linked.customer", PASSWORD, email=None, now=NOW)
    db.flush()
    return service, result.user_id, result.session_id


def test_web_first_link_stores_only_hash_consumes_once_and_keeps_original_user(db: Session) -> None:
    service, user_id, session_id = _password_account(db)
    raw, expires = service.create_telegram_link_challenge(user_id, session_id, PASSWORD, now=NOW)
    db.flush()
    challenge = db.scalar(select(TelegramLinkChallengeModel))
    assert challenge is not None
    assert challenge.token_hash != raw
    assert raw not in repr(challenge.__dict__)
    assert expires == NOW + timedelta(seconds=600)
    service.verifier = FakeVerifier(901, raw)  # type: ignore[assignment]
    result = service.complete_telegram_link(raw, "signed-init-data", now=NOW)
    db.flush()
    assert result.user_id == user_id
    assert db.scalar(select(TelegramAccountModel)).user_id == user_id  # type: ignore[union-attr]
    assert db.scalar(select(func.count()).select_from(UserModel)) == 1
    assert challenge.consumed_at == NOW
    assert raw not in repr(db.scalars(select(SecurityEventModel)).all())
    with pytest.raises(AccountLinkConflict):
        service.complete_telegram_link(raw, "signed-init-data", now=NOW)


def test_challenge_creation_invalidates_previous_and_expired_challenge_fails(db: Session) -> None:
    service, user_id, session_id = _password_account(db)
    first, _ = service.create_telegram_link_challenge(user_id, session_id, PASSWORD, now=NOW)
    second, _ = service.create_telegram_link_challenge(
        user_id, session_id, PASSWORD, now=NOW + timedelta(seconds=1)
    )
    db.flush()
    active = db.scalars(
        select(TelegramLinkChallengeModel).where(TelegramLinkChallengeModel.consumed_at.is_(None))
    ).all()
    assert len(active) == 1
    assert service.tokens.verify(second, active[0].token_hash)
    assert not service.tokens.verify(first, active[0].token_hash)
    service.verifier = FakeVerifier(902, second)  # type: ignore[assignment]
    with pytest.raises(AccountLinkConflict):
        service.complete_telegram_link(second, "signed-init-data", now=NOW + timedelta(minutes=11))


def test_completion_rejects_wrong_signed_start_param_and_owned_identity(db: Session) -> None:
    service, user_id, session_id = _password_account(db)
    raw, _ = service.create_telegram_link_challenge(user_id, session_id, PASSWORD, now=NOW)
    service.verifier = FakeVerifier(903, "wrong")  # type: ignore[assignment]
    with pytest.raises(AccountLinkConflict):
        service.complete_telegram_link(raw, "signed-init-data", now=NOW)
    other = UserModel(status="ACTIVE", created_at=NOW, updated_at=NOW)
    db.add(other)
    db.flush()
    db.add(
        TelegramAccountModel(
            telegram_user_id=903,
            user_id=other.id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    )
    db.flush()
    service.verifier = FakeVerifier(903, raw)  # type: ignore[assignment]
    with pytest.raises(AccountLinkConflict):
        service.complete_telegram_link(raw, "signed-init-data", now=NOW)
    owned = db.scalar(
        select(TelegramAccountModel).where(TelegramAccountModel.telegram_user_id == 903)
    )
    assert owned is not None and owned.user_id == other.id


def test_telegram_first_enrollment_and_password_login_use_same_user(db: Session) -> None:
    service = _service(db)
    telegram = TelegramInitData(TelegramUser(904, "tg", "Customer", None, "fa", None), NOW, None)
    user = service._link_identity(telegram, now=NOW)  # pyright: ignore[reportPrivateUsage]
    user.status = "ACTIVE"
    db.flush()
    service.verifier = FakeVerifier(904)  # type: ignore[assignment]
    service.enroll_web_credentials(user.id, "web.customer", PASSWORD, "signed-init-data", now=NOW)
    db.flush()
    credential = db.get(AccountCredentialModel, user.id)
    assert credential is not None and credential.password_hash.startswith("$argon2id$")
    assert service.authenticate_password("web.customer", PASSWORD, now=NOW).user_id == user.id
    original_hash = credential.password_hash
    with pytest.raises(AccountLinkConflict):
        service.enroll_web_credentials(
            user.id, "replacement", PASSWORD + " new", "signed-init-data", now=NOW
        )
    assert credential.password_hash == original_hash


def test_unlink_revokes_all_sessions_then_unowned_row_creates_separate_user(db: Session) -> None:
    service, user_id, session_id = _password_account(db)
    db.add(
        TelegramAccountModel(
            telegram_user_id=905,
            user_id=user_id,
            first_seen_at=NOW,
            last_seen_at=NOW,
        )
    )
    user = db.get(UserModel, user_id)
    assert user is not None
    second = service.issue_session(user, now=NOW, device_label="second")
    db.flush()
    service.unlink_telegram(user_id, PASSWORD, now=NOW)
    db.flush()
    telegram_row = db.scalar(select(TelegramAccountModel))
    assert telegram_row is not None and telegram_row.user_id is None
    for session_id_value in (session_id, second.session_id):
        session = db.get(CustomerSessionModel, session_id_value)
        assert session is not None and session.revocation_reason == "telegram_unlink"
    new_user = service._link_identity(  # pyright: ignore[reportPrivateUsage]
        TelegramInitData(TelegramUser(905, "tg", "New", None, "fa", None), NOW, None),
        now=NOW,
    )
    db.flush()
    assert new_user.id != user_id
    assert telegram_row.user_id == new_user.id
    assert db.get(AccountCredentialModel, user_id) is not None
