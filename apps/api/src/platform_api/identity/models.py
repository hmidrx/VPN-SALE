from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class IdentityBase(DeclarativeBase):
    type_annotation_map = {dict[str, object]: JSON().with_variant(JSONB, "postgresql")}


class UserModel(IdentityBase):
    __tablename__ = "identity_users"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "status in ('PENDING','ACTIVE','SUSPENDED','BLOCKED','DEACTIVATED')",
            name="ck_identity_users_status",
        ),
        Index("ix_identity_users_status", "status"),
    )


class CustomerProfileModel(IdentityBase):
    __tablename__ = "customer_profiles"
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), primary_key=True
    )
    display_name: Mapped[str | None] = mapped_column(String(160))
    locale: Mapped[str | None] = mapped_column(String(16))


class AccountCredentialModel(IdentityBase):
    __tablename__ = "account_credentials"
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), primary_key=True
    )
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "failed_login_count >= 0", name="ck_account_credentials_failed_login_count"
        ),
        CheckConstraint("credential_version > 0", name="ck_account_credentials_version"),
        CheckConstraint("password_hash LIKE '$argon2id$%'", name="ck_account_credentials_argon2id"),
    )


class AccountEmailModel(IdentityBase):
    __tablename__ = "account_emails"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("identity_users.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TelegramAccountModel(IdentityBase):
    __tablename__ = "telegram_accounts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT")
    )
    username: Mapped[str | None] = mapped_column(String(32))
    first_name: Mapped[str | None] = mapped_column(String(128))
    last_name: Mapped[str | None] = mapped_column(String(128))
    language_code: Mapped[str | None] = mapped_column(String(16))
    photo_url: Mapped[str | None] = mapped_column(String(512))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bot_started: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    blocked_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_attribution: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        UniqueConstraint("telegram_user_id", name="uq_telegram_accounts_telegram_user_id"),
        Index("ix_telegram_accounts_user_id", "user_id", unique=True),
        CheckConstraint("telegram_user_id > 0", name="ck_telegram_accounts_positive_id"),
    )


class TelegramLinkChallengeModel(IdentityBase):
    __tablename__ = "telegram_link_challenges"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="CASCADE"), nullable=False
    )
    initiating_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customer_sessions.id", ondelete="SET NULL")
    )
    token_hash: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint("failed_attempt_count >= 0", name="ck_telegram_link_failed_attempts"),
        Index("ix_telegram_link_challenges_user_active", "user_id", "consumed_at"),
        Index("ix_telegram_link_challenges_expires_at", "expires_at"),
    )


class AdminModel(IdentityBase):
    __tablename__ = "admins"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), unique=True
    )
    normalized_email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lock_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invitation_token_hash: Mapped[str | None] = mapped_column(String(96))
    invitation_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invitation_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invitation_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("normalized_email", name="uq_admins_normalized_email"),
        CheckConstraint(
            "status in ('INVITED','ACTIVE','LOCKED','DISABLED')", name="ck_admins_status"
        ),
        CheckConstraint("failed_login_count >= 0", name="ck_admins_failed_login_count"),
        Index("ix_admins_status", "status"),
    )


class PermissionModel(IdentityBase):
    __tablename__ = "permissions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    __table_args__ = (UniqueConstraint("code", name="uq_permissions_code"),)


class RoleModel(IdentityBase):
    __tablename__ = "roles"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    machine_name: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(240))
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("machine_name", name="uq_roles_machine_name"),
        Index("ix_roles_active", "active"),
    )


class RolePermissionModel(IdentityBase):
    __tablename__ = "role_permissions"
    role_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permissions_pair"),
    )


class AdminRoleAssignmentModel(IdentityBase):
    __tablename__ = "admin_role_assignments"
    admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("admin_id", "role_id", name="uq_admin_role_assignments_pair"),
    )


class UserRoleAssignmentModel(IdentityBase):
    __tablename__ = "user_role_assignments"
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("roles.id", ondelete="RESTRICT"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    assigned_by_admin_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="SET NULL")
    )
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role_assignments_pair"),
        Index("ix_user_role_assignments_role_id", "role_id"),
        Index("ix_user_role_assignments_assigned_by", "assigned_by_admin_id"),
    )


class CustomerSessionModel(IdentityBase):
    __tablename__ = "customer_sessions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    session_family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    parent_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("customer_sessions.id")
    )
    rotation_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(120))
    ip_metadata: Mapped[dict[str, object] | None]
    user_agent_metadata: Mapped[dict[str, object] | None]
    device_label: Mapped[str | None] = mapped_column(String(120))
    reuse_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csrf_token_hash: Mapped[str | None] = mapped_column(String(96))
    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_customer_sessions_refresh_token_hash"),
        Index("ix_customer_sessions_user_id", "user_id"),
        Index("ix_customer_sessions_family", "session_family_id"),
        CheckConstraint("rotation_sequence >= 0", name="ck_customer_sessions_rotation_sequence"),
    )


class AdminSessionModel(IdentityBase):
    __tablename__ = "admin_sessions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    session_family_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    parent_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admin_sessions.id")
    )
    rotation_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revocation_reason: Mapped[str | None] = mapped_column(String(120))
    ip_metadata: Mapped[dict[str, object] | None]
    user_agent_metadata: Mapped[dict[str, object] | None]
    device_label: Mapped[str | None] = mapped_column(String(120))
    reuse_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    csrf_token_hash: Mapped[str | None] = mapped_column(String(96))
    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_admin_sessions_refresh_token_hash"),
        Index("ix_admin_sessions_admin_id", "admin_id"),
        Index("ix_admin_sessions_family", "session_family_id"),
        CheckConstraint("rotation_sequence >= 0", name="ck_admin_sessions_rotation_sequence"),
    )


class LoginAttemptModel(IdentityBase):
    __tablename__ = "login_attempts"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_metadata: Mapped[dict[str, object] | None]
    user_agent_metadata: Mapped[dict[str, object] | None]
    __table_args__ = (
        Index("ix_login_attempts_subject", "subject_type", "subject_identifier"),
        Index("ix_login_attempts_occurred_at", "occurred_at"),
    )


class SecurityEventModel(IdentityBase):
    __tablename__ = "security_events"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    actor_type: Mapped[str | None] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(80))
    event_code: Mapped[str] = mapped_column(String(120), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120))
    ip_metadata: Mapped[dict[str, object] | None]
    user_agent_metadata: Mapped[dict[str, object] | None]
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_admin_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_admin_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT")
    )
    resolution_note: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (
        Index("ix_security_events_code_time", "event_code", "occurred_at"),
        Index("ix_security_events_status", "status"),
    )


class AuditLogModel(IdentityBase):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(80))
    target_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(80))
    event_code: Mapped[str] = mapped_column(String(120), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(120))
    ip_metadata: Mapped[dict[str, object] | None]
    user_agent_metadata: Mapped[dict[str, object] | None]
    metadata_: Mapped[dict[str, object]] = mapped_column(
        "metadata", JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    __table_args__ = (
        Index("ix_audit_logs_target", "target_type", "target_id"),
        Index("ix_audit_logs_code_time", "event_code", "occurred_at"),
    )


class TotpCredentialModel(IdentityBase):
    __tablename__ = "totp_credentials"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="RESTRICT"), nullable=False
    )
    encrypted_secret: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accepted_time_step: Mapped[int | None] = mapped_column(Integer)
    __table_args__ = (Index("ix_totp_credentials_admin_id", "admin_id"),)


class RecoveryCodeModel(IdentityBase):
    __tablename__ = "recovery_codes"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    credential_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("totp_credentials.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("credential_id", "code_hash", name="uq_recovery_codes_credential_hash"),
    )


class MfaChallengeModel(IdentityBase):
    __tablename__ = "admin_mfa_challenges"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    admin_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("admins.id", ondelete="CASCADE"), nullable=False
    )
    challenge_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_metadata: Mapped[dict[str, object] | None]
    user_agent_metadata: Mapped[dict[str, object] | None]
    __table_args__ = (
        UniqueConstraint("challenge_hash", name="uq_admin_mfa_challenges_hash"),
        Index("ix_admin_mfa_challenges_admin", "admin_id", "expires_at"),
    )
