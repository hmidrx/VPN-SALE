from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.identity import Admin, AdminStatus, AuditLog, TelegramAccount, User, UserStatus

from platform_api.identity.models import (
    AdminModel,
    AuditLogModel,
    CustomerSessionModel,
    IdentityBase,
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.identity.rbac_seed import INITIAL_PERMISSIONS, INITIAL_ROLES, seed_initial_rbac
from platform_api.identity.repositories import SqlAlchemyIdentityRepository
from platform_api.identity.security import OpaqueTokenService

TEST_PASSWORD_HASH = "$argon2id$test"  # noqa: S105


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine("sqlite:///:memory:")
    IdentityBase.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_unique_constraints_and_seed_idempotency(session: Session) -> None:
    seed_initial_rbac(session)
    seed_initial_rbac(session)
    assert (
        session.scalar(select(PermissionModel).where(PermissionModel.code == "admins.read"))
        is not None
    )
    assert len(session.scalars(select(PermissionModel)).all()) == len(INITIAL_PERMISSIONS)
    assert len(session.scalars(select(RoleModel)).all()) == len(INITIAL_ROLES)

    session.add_all(
        [
            AdminModel(
                normalized_email="admin@example.com",
                password_hash=TEST_PASSWORD_HASH,
                status="INVITED",
            ),
            AdminModel(
                normalized_email="admin@example.com",
                password_hash=TEST_PASSWORD_HASH,
                status="INVITED",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_telegram_role_permission_and_admin_role_uniqueness(session: Session) -> None:
    session.add_all(
        [
            TelegramAccountModel(
                telegram_user_id=1, first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC)
            ),
            TelegramAccountModel(
                telegram_user_id=1, first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC)
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    admin = AdminModel(
        normalized_email="a@example.com", password_hash=TEST_PASSWORD_HASH, status="ACTIVE"
    )
    role = RoleModel(machine_name="auditor", display_name="Auditor")
    perm = PermissionModel(code="audit.read", description="Read audit")
    session.add_all([admin, role, perm])
    session.flush()
    session.add_all(
        [
            RolePermissionModel(role_id=role.id, permission_id=perm.id),
            RolePermissionModel(role_id=role.id, permission_id=perm.id),
        ]
    )
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_repository_create_read_update_and_audit_append(session: Session) -> None:
    repo = SqlAlchemyIdentityRepository(session)
    user = repo.create_user(User(id=uuid4(), status=UserStatus.PENDING))
    loaded_user = repo.get_user(user.id)
    assert loaded_user is not None
    assert loaded_user.id == user.id
    assert loaded_user.status == user.status
    admin = repo.create_admin(
        Admin(
            id=uuid4(),
            email="Admin@Example.com",
            password_hash=TEST_PASSWORD_HASH,
            status=AdminStatus.INVITED,
        )
    )
    loaded_admin = repo.find_admin_by_email(" admin@example.COM ")
    assert loaded_admin is not None
    assert loaded_admin.id == admin.id
    assert loaded_admin.email == admin.email
    account = TelegramAccount(telegram_user_id=99, user_id=user.id, username="@User")
    repo.upsert_telegram_account(account)
    loaded_account = repo.find_telegram_account_by_telegram_id(99)
    assert loaded_account is not None
    assert loaded_account.telegram_user_id == account.telegram_user_id
    assert loaded_account.user_id == account.user_id
    event = AuditLog(
        id=uuid4(),
        actor_type="admin",
        actor_id=str(admin.id),
        target_type="user",
        target_id=str(user.id),
        event_code="users.read",
        occurred_at=datetime.now(UTC),
        metadata={"reason": "support"},
    )
    repo.append_audit_event(event)
    assert session.get(AuditLogModel, str(event.id)) is not None


def test_session_persists_only_refresh_token_hash(session: Session) -> None:
    user = UserModel(id=str(uuid4()), status="ACTIVE")
    session.add(user)
    session.flush()
    token_service = OpaqueTokenService()
    raw = token_service.generate()
    token_hash = token_service.hash(raw)
    session.add(
        CustomerSessionModel(
            user_id=user.id,
            refresh_token_hash=token_hash,
            session_family_id=str(uuid4()),
            rotation_sequence=0,
            idle_expires_at=datetime.now(UTC) + timedelta(hours=1),
            absolute_expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    session.flush()
    persisted = session.scalar(select(CustomerSessionModel))
    assert persisted is not None
    assert persisted.refresh_token_hash == token_hash
    assert raw not in persisted.refresh_token_hash


def test_repository_interfaces_do_not_return_sqlalchemy_models(session: Session) -> None:
    repo = SqlAlchemyIdentityRepository(session)
    user = repo.create_user(User(id=uuid4()))
    assert isinstance(repo.get_user(user.id), User)
    assert not isinstance(repo.get_user(user.id), UserModel)
