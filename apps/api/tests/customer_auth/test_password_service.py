from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from platform_api.config import Settings
from platform_api.customer_auth.service import CustomerAuthService
from platform_api.customer_auth.telegram import TelegramInitData, TelegramUser
from platform_api.identity.models import (
    AccountCredentialModel,
    AccountEmailModel,
    CustomerSessionModel,
    IdentityBase,
    TelegramAccountModel,
    UserModel,
    UserRoleAssignmentModel,
)
from platform_api.identity.rbac_seed import seed_initial_rbac


def password(label: str = "safe") -> str:
    return " ".join(("runtime", label, "passphrase", "value"))


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    with Session(engine) as value:
        seed_initial_rbac(value)
        value.commit()
        yield value


@pytest.fixture()
def service(session: Session) -> CustomerAuthService:
    return CustomerAuthService(session, Settings(telegram_customer_auth_enabled=False))


def test_registration_creates_complete_password_identity(service: CustomerAuthService) -> None:
    result = service.register_password_account(
        "New.Customer",
        password(),
        email="Customer@Example.test",
        ip="present",
        user_agent="present",
        correlation_id="present",
    )
    service.session.flush()
    credential = service.session.scalar(select(AccountCredentialModel))
    assert credential is not None
    assert credential.normalized_username == "new.customer"
    assert credential.password_hash.startswith("$argon2id$")
    assert password() not in credential.password_hash
    assert service.session.scalar(select(AccountEmailModel)).verified_at is None  # type: ignore[union-attr]
    assert service.session.scalar(select(UserRoleAssignmentModel)) is not None
    assert service.session.scalar(select(CustomerSessionModel)).id == result.session_id  # type: ignore[union-attr]
    assert service.session.scalar(select(TelegramAccountModel)) is None


def test_registration_without_email_and_generic_conflict(service: CustomerAuthService) -> None:
    service.register_password_account("First.User", password("first"), email=None)
    service.session.flush()
    assert service.session.scalar(select(AccountEmailModel)) is None
    with pytest.raises(ValueError, match="could not be completed"):
        service.register_password_account("FIRST.USER", password("second"), email=None)
    assert len(service.session.scalars(select(UserModel)).all()) == 1


def test_password_login_success_failure_lockout_and_reset(service: CustomerAuthService) -> None:
    service.register_password_account("Login.User", password(), email=None)
    service.session.flush()
    for _ in range(2):
        with pytest.raises(ValueError, match="Invalid credentials"):
            service.authenticate_password("login.user", password("wrong"))
    credential = service.session.scalar(select(AccountCredentialModel))
    assert credential is not None and credential.failed_login_count == 2
    result = service.authenticate_password("LOGIN.USER", password())
    assert result.access_token
    assert credential.failed_login_count == 0
    assert credential.lock_until is None
    assert credential.last_successful_login_at is not None


def test_unknown_and_inactive_users_have_generic_failure(service: CustomerAuthService) -> None:
    with pytest.raises(ValueError, match="Invalid credentials"):
        service.authenticate_password("none.user", password())
    service.register_password_account("Gone.User", password(), email=None)
    user = service.session.scalar(select(UserModel))
    assert user is not None
    user.status = "SUSPENDED"
    with pytest.raises(ValueError, match="Invalid credentials"):
        service.authenticate_password("gone.user", password())


def test_lockout_activates_at_configured_threshold(session: Session) -> None:
    settings = Settings(
        telegram_customer_auth_enabled=False,
        customer_password_lockout_threshold=2,
    )
    service = CustomerAuthService(session, settings)
    service.register_password_account("Locked.User", password(), email=None, now=datetime.now(UTC))
    for _ in range(2):
        with pytest.raises(ValueError):
            service.authenticate_password("locked.user", password("wrong"))
    credential = session.scalar(select(AccountCredentialModel))
    assert credential is not None and credential.lock_until is not None


def test_new_telegram_customer_receives_only_customer_role(
    service: CustomerAuthService,
) -> None:
    now = datetime.now(UTC)
    service._link_identity(  # pyright: ignore[reportPrivateUsage]
        TelegramInitData(
            user=TelegramUser(101, "telegram_name", "Customer", None, "en", None),
            auth_date=now,
            start_param=None,
        ),
        now=now,
    )
    service.session.flush()
    assignments = service.session.scalars(select(UserRoleAssignmentModel)).all()
    assert len(assignments) == 1
