from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.identity import (
    Admin,
    AdminStatus,
    AuditLog,
    TelegramAccount,
    User,
    UserStatus,
    normalize_email,
    sanitize_metadata,
)

from .models import AdminModel, AuditLogModel, TelegramAccountModel, UserModel


class IdentityRepository(Protocol):
    def create_user(self, user: User) -> User: ...
    def get_user(self, user_id: UUID) -> User | None: ...
    def create_admin(self, admin: Admin) -> Admin: ...
    def find_admin_by_email(self, email: str) -> Admin | None: ...
    def upsert_telegram_account(self, account: TelegramAccount) -> TelegramAccount: ...
    def find_telegram_account_by_telegram_id(
        self, telegram_user_id: int
    ) -> TelegramAccount | None: ...
    def append_audit_event(self, event: AuditLog) -> AuditLog: ...


class SqlAlchemyIdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_user(self, user: User) -> User:
        self._session.add(
            UserModel(
                id=str(user.id),
                status=user.status.value,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
        )
        self._session.flush()
        return user

    def get_user(self, user_id: UUID) -> User | None:
        row = self._session.get(UserModel, str(user_id))
        return (
            None
            if row is None
            else User(
                id=UUID(row.id),
                status=UserStatus(row.status),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    def create_admin(self, admin: Admin) -> Admin:
        self._session.add(
            AdminModel(
                id=str(admin.id),
                normalized_email=admin.email,
                password_hash=admin.password_hash,
                status=admin.status.value,
                failed_login_count=admin.failed_login_count,
                lock_until=admin.lock_until,
                last_successful_login_at=admin.last_successful_login_at,
                last_failed_login_at=admin.last_failed_login_at,
                password_changed_at=admin.password_changed_at,
                created_at=admin.created_at,
                updated_at=admin.updated_at,
            )
        )
        self._session.flush()
        return admin

    def find_admin_by_email(self, email: str) -> Admin | None:
        row = self._session.scalar(
            select(AdminModel).where(AdminModel.normalized_email == normalize_email(email))
        )
        return (
            None
            if row is None
            else Admin(
                id=UUID(row.id),
                email=row.normalized_email,
                password_hash=row.password_hash,
                status=AdminStatus(row.status),
                failed_login_count=row.failed_login_count,
                lock_until=row.lock_until,
                last_successful_login_at=row.last_successful_login_at,
                last_failed_login_at=row.last_failed_login_at,
                password_changed_at=row.password_changed_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )

    def upsert_telegram_account(self, account: TelegramAccount) -> TelegramAccount:
        row = self._session.scalar(
            select(TelegramAccountModel).where(
                TelegramAccountModel.telegram_user_id == account.telegram_user_id
            )
        )
        if row is None:
            row = TelegramAccountModel(
                id=str(uuid4()),
                telegram_user_id=account.telegram_user_id,
                first_seen_at=account.first_seen_at,
                last_seen_at=account.last_seen_at,
            )
            self._session.add(row)
        row.user_id = str(account.user_id) if account.user_id else None
        row.username = account.username
        row.first_name = account.first_name
        row.last_name = account.last_name
        row.language_code = account.language_code
        row.photo_url = account.photo_url
        row.last_seen_at = account.last_seen_at
        row.bot_started = account.bot_started
        row.blocked_bot = account.blocked_bot
        row.start_attribution = account.start_attribution
        self._session.flush()
        return account

    def find_telegram_account_by_telegram_id(self, telegram_user_id: int) -> TelegramAccount | None:
        row = self._session.scalar(
            select(TelegramAccountModel).where(
                TelegramAccountModel.telegram_user_id == telegram_user_id
            )
        )
        return (
            None
            if row is None
            else TelegramAccount(
                telegram_user_id=row.telegram_user_id,
                user_id=UUID(row.user_id) if row.user_id else None,
                username=row.username,
                first_name=row.first_name,
                last_name=row.last_name,
                language_code=row.language_code,
                photo_url=row.photo_url,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                bot_started=row.bot_started,
                blocked_bot=row.blocked_bot,
                start_attribution=row.start_attribution,
            )
        )

    def append_audit_event(self, event: AuditLog) -> AuditLog:
        self._session.add(
            AuditLogModel(
                id=str(event.id),
                actor_type=event.actor_type,
                actor_id=event.actor_id,
                target_type=event.target_type,
                target_id=event.target_id,
                event_code=event.event_code,
                occurred_at=event.occurred_at,
                metadata_=sanitize_metadata(event.metadata),
            )
        )
        self._session.flush()
        return event


def now_utc() -> datetime:
    return datetime.now(UTC)
