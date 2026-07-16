from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PERMISSION_CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")
SENSITIVE_KEY_RE = re.compile(
    r"(password|secret|token|credential|hash|init[_-]?data|recovery|totp)", re.I
)
SENSITIVE_VALUE_RE = re.compile(r"(bearer\s+|-----BEGIN|password=|token=|secret=)", re.I)


def utc_now() -> datetime:
    return datetime.now(UTC)


class InvalidStatusTransition(ValueError):
    pass


class SensitiveMetadataError(ValueError):
    pass


class UserStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BLOCKED = "BLOCKED"
    DEACTIVATED = "DEACTIVATED"


USER_STATUS_TRANSITIONS: dict[UserStatus, frozenset[UserStatus]] = {
    UserStatus.PENDING: frozenset({UserStatus.ACTIVE, UserStatus.DEACTIVATED}),
    UserStatus.ACTIVE: frozenset(
        {UserStatus.SUSPENDED, UserStatus.BLOCKED, UserStatus.DEACTIVATED}
    ),
    UserStatus.SUSPENDED: frozenset(
        {UserStatus.ACTIVE, UserStatus.BLOCKED, UserStatus.DEACTIVATED}
    ),
    UserStatus.BLOCKED: frozenset(),
    UserStatus.DEACTIVATED: frozenset(),
}


class AdminStatus(StrEnum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    DISABLED = "DISABLED"


ADMIN_STATUS_TRANSITIONS: dict[AdminStatus, frozenset[AdminStatus]] = {
    AdminStatus.INVITED: frozenset({AdminStatus.ACTIVE, AdminStatus.DISABLED}),
    AdminStatus.ACTIVE: frozenset({AdminStatus.LOCKED, AdminStatus.DISABLED}),
    AdminStatus.LOCKED: frozenset({AdminStatus.ACTIVE, AdminStatus.DISABLED}),
    AdminStatus.DISABLED: frozenset(),
}


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if not EMAIL_RE.fullmatch(normalized):
        raise ValueError("invalid administrator email")
    return normalized


def normalize_optional_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    return normalized[:max_length]


def normalize_username(value: str | None) -> str | None:
    normalized = normalize_optional_text(value.removeprefix("@") if value else None, max_length=32)
    return normalized.casefold() if normalized else None


def validate_permission_code(code: str) -> str:
    if not PERMISSION_CODE_RE.fullmatch(code):
        raise ValueError("permission code must be a stable dotted machine string")
    return code


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        if SENSITIVE_KEY_RE.search(key):
            raise SensitiveMetadataError(f"sensitive metadata key rejected: {key}")
        if isinstance(value, str) and SENSITIVE_VALUE_RE.search(value):
            raise SensitiveMetadataError(f"sensitive metadata value rejected: {key}")
        if isinstance(value, dict):
            sanitized[key] = sanitize_metadata(cast(dict[str, Any], value))
        elif isinstance(value, str | int | bool) or value is None:
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized


def ensure_transition(current: UserStatus | AdminStatus, target: UserStatus | AdminStatus) -> None:
    if current == target:
        return
    if isinstance(current, UserStatus) and isinstance(target, UserStatus):
        allowed = USER_STATUS_TRANSITIONS[current]
    elif isinstance(current, AdminStatus) and isinstance(target, AdminStatus):
        allowed = ADMIN_STATUS_TRANSITIONS[current]
    else:
        raise InvalidStatusTransition(f"illegal status transition: {current} -> {target}")
    if target not in allowed:
        raise InvalidStatusTransition(f"illegal status transition: {current} -> {target}")


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    status: UserStatus = UserStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def transition_to(self, target: UserStatus, *, at: datetime | None = None) -> User:
        ensure_transition(self.status, target)
        return User(
            id=self.id, status=target, created_at=self.created_at, updated_at=at or utc_now()
        )


@dataclass(frozen=True, slots=True)
class CustomerProfile:
    user_id: UUID
    display_name: str | None = None
    locale: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramAccount:
    telegram_user_id: int
    user_id: UUID | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    photo_url: str | None = None
    first_seen_at: datetime = field(default_factory=utc_now)
    last_seen_at: datetime = field(default_factory=utc_now)
    bot_started: bool = False
    blocked_bot: bool = False
    start_attribution: str | None = None

    def __post_init__(self) -> None:
        if self.telegram_user_id <= 0:
            raise ValueError("Telegram user ID must be positive")
        object.__setattr__(self, "username", normalize_username(self.username))
        object.__setattr__(
            self, "first_name", normalize_optional_text(self.first_name, max_length=128)
        )
        object.__setattr__(
            self, "last_name", normalize_optional_text(self.last_name, max_length=128)
        )
        object.__setattr__(
            self, "language_code", normalize_optional_text(self.language_code, max_length=16)
        )
        object.__setattr__(
            self, "photo_url", normalize_optional_text(self.photo_url, max_length=512)
        )
        object.__setattr__(
            self,
            "start_attribution",
            normalize_optional_text(self.start_attribution, max_length=128),
        )


@dataclass(frozen=True, slots=True)
class Admin:
    id: UUID
    email: str
    password_hash: str
    status: AdminStatus = AdminStatus.INVITED
    failed_login_count: int = 0
    lock_until: datetime | None = None
    last_successful_login_at: datetime | None = None
    last_failed_login_at: datetime | None = None
    password_changed_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        object.__setattr__(self, "email", normalize_email(self.email))

    def transition_to(self, target: AdminStatus, *, at: datetime | None = None) -> Admin:
        ensure_transition(self.status, target)
        return Admin(
            id=self.id,
            email=self.email,
            password_hash=self.password_hash,
            status=target,
            failed_login_count=self.failed_login_count,
            lock_until=self.lock_until,
            last_successful_login_at=self.last_successful_login_at,
            last_failed_login_at=self.last_failed_login_at,
            password_changed_at=self.password_changed_at,
            created_at=self.created_at,
            updated_at=at or utc_now(),
        )


@dataclass(frozen=True, slots=True)
class Permission:
    code: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", validate_permission_code(self.code))


@dataclass(frozen=True, slots=True)
class Role:
    machine_name: str
    display_name: str


@dataclass(frozen=True, slots=True)
class RolePermission:
    role_id: UUID
    permission_id: UUID


@dataclass(frozen=True, slots=True)
class AdminRoleAssignment:
    admin_id: UUID
    role_id: UUID


@dataclass(frozen=True, slots=True)
class CustomerSession:
    id: UUID
    user_id: UUID
    refresh_token_hash: str
    session_family_id: UUID
    rotation_sequence: int
    absolute_expires_at: datetime
    idle_expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AdminSession:
    id: UUID
    admin_id: UUID
    refresh_token_hash: str
    session_family_id: UUID
    rotation_sequence: int
    absolute_expires_at: datetime
    idle_expires_at: datetime
    revoked_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LoginAttempt:
    id: UUID
    subject_type: str
    subject_identifier: str
    succeeded: bool
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    id: UUID
    event_code: str
    occurred_at: datetime
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class AuditLog:
    id: UUID
    actor_type: str
    actor_id: str | None
    target_type: str
    target_id: str | None
    event_code: str
    occurred_at: datetime
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", sanitize_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class TotpCredential:
    id: UUID
    admin_id: UUID
    encrypted_secret: str
    key_version: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RecoveryCode:
    id: UUID
    credential_id: UUID
    code_hash: str
    used_at: datetime | None = None
