from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

import jwt
import pyotp
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from vpnsale_domain.identity import AdminStatus, normalize_email, sanitize_metadata

from platform_api.config import Settings
from platform_api.identity.models import (
    AdminModel,
    AdminRoleAssignmentModel,
    AdminSessionModel,
    AuditLogModel,
    LoginAttemptModel,
    MfaChallengeModel,
    PermissionModel,
    RecoveryCodeModel,
    RoleModel,
    RolePermissionModel,
    SecurityEventModel,
    TotpCredentialModel,
)
from platform_api.identity.rbac_seed import INITIAL_PERMISSIONS, seed_initial_rbac
from platform_api.identity.security import (
    EncryptedSecret,
    FernetSecretEncryptor,
    OpaqueTokenService,
    PasswordHasherProtocol,
)

GENERIC_AUTH_ERROR = "Invalid credentials or authentication state"


class AuthenticationOutcome(StrEnum):
    AUTHENTICATED = "AUTHENTICATED"
    MFA_REQUIRED = "MFA_REQUIRED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    RATE_LIMITED = "RATE_LIMITED"


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    min_length: int = 14
    max_length: int = 512
    common_passwords: frozenset[str] = frozenset(
        {"password", "password123", "admin123", "qwerty123", "letmein", "123456789"}
    )

    def validate(self, password: str, *, email: str) -> None:
        normalized_email = normalize_email(email)
        text = password.strip()
        if len(password) > self.max_length:
            raise ValueError("password is too long")
        if len(text) < self.min_length:
            raise ValueError("password is too short")
        folded = text.casefold()
        if folded in self.common_passwords:
            raise ValueError("password is too common")
        local = normalized_email.split("@", 1)[0]
        if (
            folded == normalized_email
            or normalized_email in folded
            or (len(local) >= 4 and local in folded)
        ):
            raise ValueError("password must not contain the administrator email identity")


class FixedWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, tuple[int, datetime]] = {}

    def check(self, key: str, now: datetime) -> tuple[bool, int]:
        count, start = self._hits.get(key, (0, now))
        if now >= start + timedelta(seconds=self.window_seconds):
            count, start = 0, now
        count += 1
        self._hits[key] = (count, start)
        retry = max(1, int((start + timedelta(seconds=self.window_seconds) - now).total_seconds()))
        return count <= self.limit, retry


def _cmp(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def hardened_rate_key(purpose: str, *parts: str, salt: str) -> str:
    raw = ":".join([purpose, *parts]).casefold().encode()
    return purpose + ":" + hmac.new(salt.encode(), raw, hashlib.sha256).hexdigest()


class AccessTokenService:
    algorithm = "HS256"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def issue(self, *, admin_id: str, session_id: str, now: datetime) -> str:
        exp = now + timedelta(seconds=self.settings.admin_access_token_lifetime_seconds)
        payload = {
            "iss": self.settings.admin_access_token_issuer,
            "aud": self.settings.admin_access_token_audience,
            "sub": admin_id,
            "sid": session_id,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            "jti": str(uuid4()),
        }
        return jwt.encode(
            payload,
            self.settings.admin_access_token_signing_key,
            algorithm=self.algorithm,
            headers={"kid": self.settings.admin_access_token_key_id},
        )

    def validate(self, token: str) -> dict[str, str]:
        try:
            claims = jwt.decode(
                token,
                self.settings.admin_access_token_signing_key,
                algorithms=[self.algorithm],
                issuer=self.settings.admin_access_token_issuer,
                audience=self.settings.admin_access_token_audience,
                leeway=self.settings.admin_access_token_clock_skew_seconds,
            )
        except jwt.PyJWTError as exc:
            raise ValueError(GENERIC_AUTH_ERROR) from exc
        return {
            "admin_id": str(claims["sub"]),
            "session_id": str(claims["sid"]),
            "jti": str(claims["jti"]),
        }


def _event(
    session: Session,
    model: type[AuditLogModel] | type[SecurityEventModel],
    code: str,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, object] | None = None,
    now: datetime,
) -> None:
    safe = sanitize_metadata(metadata or {})
    if model is AuditLogModel:
        session.add(
            AuditLogModel(
                actor_type="admin" if actor_id else "system",
                actor_id=actor_id,
                target_type="admin",
                target_id=target_id,
                event_code=code,
                occurred_at=now,
                metadata_=safe,
            )
        )
    else:
        session.add(
            SecurityEventModel(
                actor_type="admin" if actor_id else "system",
                actor_id=actor_id,
                event_code=code,
                occurred_at=now,
                metadata_=safe,
            )
        )


def _all_permissions_to_super_admin(session: Session) -> None:
    super_role = session.scalar(select(RoleModel).where(RoleModel.machine_name == "super_admin"))
    if super_role is None:
        raise RuntimeError("super_admin role missing")
    for code, _ in INITIAL_PERMISSIONS:
        perm = session.scalar(select(PermissionModel).where(PermissionModel.code == code))
        if perm and not session.get(
            RolePermissionModel, {"role_id": super_role.id, "permission_id": perm.id}
        ):
            session.add(RolePermissionModel(role_id=super_role.id, permission_id=perm.id))
    session.flush()


class AdminAuthService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        hasher: PasswordHasherProtocol,
        limiter: FixedWindowRateLimiter | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.hasher = hasher
        self.tokens = OpaqueTokenService(
            settings.opaque_token_bytes, settings.opaque_token_hash_salt
        )
        self.access = AccessTokenService(settings)
        self.limiter = limiter

    def bootstrap_admin(self, email: str, password: str, *, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        email_n = normalize_email(email)
        PasswordPolicy(
            self.settings.admin_password_min_length, self.settings.admin_password_max_length
        ).validate(password, email=email_n)
        if (
            self.session.scalar(
                select(AdminModel).where(AdminModel.status == AdminStatus.ACTIVE.value)
            )
            is not None
        ):
            _event(
                self.session,
                AuditLogModel,
                "admin.bootstrap.rejected",
                metadata={"reason": "active_super_admin_exists"},
                now=now,
            )
            raise ValueError("active Super Admin already exists")
        if (
            self.session.scalar(select(AdminModel).where(AdminModel.normalized_email == email_n))
            is not None
        ):
            _event(
                self.session,
                AuditLogModel,
                "admin.bootstrap.rejected",
                metadata={"reason": "duplicate_email"},
                now=now,
            )
            raise ValueError("administrator email already exists")
        seed_initial_rbac(self.session)
        _all_permissions_to_super_admin(self.session)
        admin = AdminModel(
            normalized_email=email_n,
            password_hash=self.hasher.hash(password),
            status=AdminStatus.ACTIVE.value,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(admin)
        self.session.flush()
        role = self.session.scalar(select(RoleModel).where(RoleModel.machine_name == "super_admin"))
        if role is None:
            raise RuntimeError("super_admin role missing")
        self.session.add(AdminRoleAssignmentModel(admin_id=admin.id, role_id=role.id))
        _event(
            self.session, AuditLogModel, "admin.bootstrap.succeeded", target_id=admin.id, now=now
        )
        _event(
            self.session,
            SecurityEventModel,
            "admin.bootstrap.succeeded",
            target_id=admin.id,
            now=now,
        )
        return str(admin.id)

    def login(
        self,
        email: str,
        password: str,
        *,
        ip: str = "",
        user_agent: str = "",
        now: datetime | None = None,
    ) -> dict[str, object]:
        now = now or datetime.now(UTC)
        email_n = normalize_email(email)
        key = hardened_rate_key(
            "admin-login", email_n, ip, salt=self.settings.opaque_token_hash_salt
        )
        if self.limiter:
            ok, retry = self.limiter.check(key, now)
            if not ok:
                _event(
                    self.session,
                    SecurityEventModel,
                    "admin.login.rate_limited",
                    metadata={"subject": "admin"},
                    now=now,
                )
                return {"outcome": AuthenticationOutcome.RATE_LIMITED, "retry_after": retry}
        admin = self.session.scalar(
            select(AdminModel).where(AdminModel.normalized_email == email_n)
        )
        self.session.add(
            LoginAttemptModel(
                subject_type="admin",
                subject_identifier=key,
                succeeded=False,
                occurred_at=now,
                ip_metadata={
                    "hash": hardened_rate_key("ip", ip, salt=self.settings.opaque_token_hash_salt)
                }
                if ip
                else None,
                user_agent_metadata={"present": bool(user_agent)},
            )
        )
        if (
            admin is None
            or admin.status in {AdminStatus.DISABLED.value, AdminStatus.INVITED.value}
            or (admin.lock_until and _cmp(admin.lock_until) > now)
            or not self.hasher.verify(password, admin.password_hash)
        ):
            if admin and self.hasher.verify(password, admin.password_hash) is False:
                admin.failed_login_count += 1
                admin.last_failed_login_at = now
                if admin.failed_login_count >= self.settings.admin_lockout_threshold:
                    admin.lock_until = now + timedelta(
                        seconds=self.settings.admin_lockout_duration_seconds
                    )
                    _event(
                        self.session,
                        SecurityEventModel,
                        "admin.login.locked",
                        actor_id=admin.id,
                        now=now,
                    )
            _event(
                self.session,
                SecurityEventModel,
                "admin.login.failed",
                actor_id=admin.id if admin else None,
                metadata={"reason": "generic"},
                now=now,
            )
            return {"outcome": AuthenticationOutcome.INVALID_CREDENTIALS}
        if self.hasher.needs_rehash(admin.password_hash):
            admin.password_hash = self.hasher.hash(password)
        admin.failed_login_count = 0
        admin.lock_until = None
        admin.last_successful_login_at = now
        active_totp = self.session.scalar(
            select(TotpCredentialModel).where(
                TotpCredentialModel.admin_id == admin.id,
                TotpCredentialModel.revoked_at.is_(None),
                TotpCredentialModel.confirmed_at.is_not(None),
            )
        )
        if active_totp:
            token = self.tokens.generate()
            self.session.add(
                MfaChallengeModel(
                    admin_id=admin.id,
                    challenge_hash=self.tokens.hash(token),
                    expires_at=now
                    + timedelta(seconds=self.settings.admin_mfa_challenge_lifetime_seconds),
                    created_at=now,
                    ip_metadata={
                        "hash": hardened_rate_key(
                            "ip", ip, salt=self.settings.opaque_token_hash_salt
                        )
                    }
                    if ip
                    else None,
                    user_agent_metadata={"present": bool(user_agent)},
                )
            )
            _event(
                self.session,
                SecurityEventModel,
                "admin.mfa.challenge.created",
                actor_id=admin.id,
                now=now,
            )
            return {"outcome": AuthenticationOutcome.MFA_REQUIRED, "mfa_challenge": token}
        return {
            "outcome": AuthenticationOutcome.AUTHENTICATED,
            **self._create_session(admin, now=now, ip=ip, user_agent=user_agent),
        }

    def _create_session(
        self, admin: AdminModel, *, now: datetime, ip: str = "", user_agent: str = ""
    ) -> dict[str, str]:
        raw = self.tokens.generate()
        sid = str(uuid4())
        fam = str(uuid4())
        sess = AdminSessionModel(
            id=sid,
            admin_id=admin.id,
            refresh_token_hash=self.tokens.hash(raw),
            session_family_id=fam,
            rotation_sequence=0,
            created_at=now,
            last_used_at=now,
            idle_expires_at=now
            + timedelta(seconds=self.settings.admin_session_idle_timeout_seconds),
            absolute_expires_at=now
            + timedelta(seconds=self.settings.admin_session_absolute_lifetime_seconds),
            ip_metadata={
                "hash": hardened_rate_key("ip", ip, salt=self.settings.opaque_token_hash_salt)
            }
            if ip
            else None,
            user_agent_metadata={"present": bool(user_agent)},
        )
        csrf_token = self.csrf_for(sid)
        sess.csrf_token_hash = csrf_token
        self.session.add(sess)
        _event(
            self.session,
            AuditLogModel,
            "admin.session.created",
            actor_id=admin.id,
            target_id=sid,
            now=now,
        )
        _event(
            self.session, SecurityEventModel, "admin.login.succeeded", actor_id=admin.id, now=now
        )
        return {
            "access_token": self.access.issue(admin_id=admin.id, session_id=sid, now=now),
            "refresh_token": raw,
            "csrf_token": csrf_token,
        }

    def csrf_for(self, session_id: str) -> str:
        return self.tokens.hash(f"csrf:{session_id}:{self.settings.admin_csrf_secret}")

    def verify_mfa(
        self, challenge: str, code: str, *, now: datetime | None = None
    ) -> dict[str, object]:
        now = now or datetime.now(UTC)
        ch = self.session.scalar(
            select(MfaChallengeModel).where(
                MfaChallengeModel.challenge_hash == self.tokens.hash(challenge)
            )
        )
        if not ch or ch.consumed_at or _cmp(ch.expires_at) < now:
            return {"outcome": AuthenticationOutcome.INVALID_CREDENTIALS}
        admin = self.session.get(AdminModel, ch.admin_id)
        cred = self.session.scalar(
            select(TotpCredentialModel).where(
                TotpCredentialModel.admin_id == ch.admin_id,
                TotpCredentialModel.revoked_at.is_(None),
                TotpCredentialModel.confirmed_at.is_not(None),
            )
        )
        if not admin or not cred:
            return {"outcome": AuthenticationOutcome.INVALID_CREDENTIALS}
        if not self._valid_totp_or_recovery(cred, code, now=now):
            _event(
                self.session,
                SecurityEventModel,
                "admin.mfa.challenge.failed",
                actor_id=admin.id,
                now=now,
            )
            return {"outcome": AuthenticationOutcome.INVALID_CREDENTIALS}
        ch.consumed_at = now
        _event(self.session, SecurityEventModel, "admin.mfa.succeeded", actor_id=admin.id, now=now)
        return {
            "outcome": AuthenticationOutcome.AUTHENTICATED,
            **self._create_session(admin, now=now),
        }

    def _valid_totp_or_recovery(
        self, cred: TotpCredentialModel, code: str, *, now: datetime
    ) -> bool:
        enc = FernetSecretEncryptor(
            self.settings.identity_encryption_key, self.settings.identity_encryption_key_version
        )
        secret = enc.decrypt(EncryptedSecret(cred.key_version, cred.encrypted_secret))
        step = int(now.timestamp() // 30)
        if pyotp.TOTP(secret).verify(
            code, for_time=now, valid_window=self.settings.admin_totp_clock_window
        ):
            if cred.last_accepted_time_step == step:
                return False
            cred.last_accepted_time_step = step
            return True
        for rc in self.session.scalars(
            select(RecoveryCodeModel).where(
                RecoveryCodeModel.credential_id == cred.id, RecoveryCodeModel.used_at.is_(None)
            )
        ).all():
            if self.tokens.verify(code, rc.code_hash):
                rc.used_at = now
                _event(
                    self.session,
                    AuditLogModel,
                    "admin.recovery_code.used",
                    actor_id=cred.admin_id,
                    target_id=cred.id,
                    now=now,
                )
                return True
        return False

    def session_for_refresh(self, refresh_token: str) -> AdminSessionModel | None:
        return self.session.scalar(
            select(AdminSessionModel).where(
                AdminSessionModel.refresh_token_hash == self.tokens.hash(refresh_token)
            )
        )

    def refresh(self, refresh_token: str, *, now: datetime | None = None) -> dict[str, str]:
        now = now or datetime.now(UTC)
        h = self.tokens.hash(refresh_token)
        sess = self.session.scalar(
            select(AdminSessionModel).where(AdminSessionModel.refresh_token_hash == h)
        )
        if not sess:
            raise ValueError(GENERIC_AUTH_ERROR)
        if sess.consumed_at is not None:
            self._revoke_family(sess.session_family_id, now, "refresh_reuse")
            sess.reuse_detected_at = now
            _event(
                self.session,
                AuditLogModel,
                "admin.refresh_reuse_detected",
                actor_id=sess.admin_id,
                target_id=sess.id,
                now=now,
            )
            _event(
                self.session,
                SecurityEventModel,
                "admin.refresh_reuse_detected",
                actor_id=sess.admin_id,
                now=now,
            )
            raise ValueError(GENERIC_AUTH_ERROR)
        if (
            sess.revoked_at
            or _cmp(sess.idle_expires_at) < now
            or _cmp(sess.absolute_expires_at) < now
        ):
            raise ValueError(GENERIC_AUTH_ERROR)
        sess.consumed_at = now
        raw = self.tokens.generate()
        next_s = AdminSessionModel(
            admin_id=sess.admin_id,
            refresh_token_hash=self.tokens.hash(raw),
            session_family_id=sess.session_family_id,
            parent_session_id=sess.id,
            rotation_sequence=sess.rotation_sequence + 1,
            created_at=now,
            last_used_at=now,
            idle_expires_at=now
            + timedelta(seconds=self.settings.admin_session_idle_timeout_seconds),
            absolute_expires_at=sess.absolute_expires_at,
            ip_metadata=sess.ip_metadata,
            user_agent_metadata=sess.user_agent_metadata,
        )
        self.session.add(next_s)
        self.session.flush()
        next_s.csrf_token_hash = self.csrf_for(next_s.id)
        _event(
            self.session,
            AuditLogModel,
            "admin.session.refreshed",
            actor_id=sess.admin_id,
            target_id=next_s.id,
            now=now,
        )
        return {
            "access_token": self.access.issue(
                admin_id=sess.admin_id, session_id=next_s.id, now=now
            ),
            "refresh_token": raw,
            "csrf_token": next_s.csrf_token_hash or self.csrf_for(next_s.id),
        }

    def _revoke_family(self, family: str, now: datetime, reason: str) -> None:
        self.session.execute(
            update(AdminSessionModel)
            .where(
                AdminSessionModel.session_family_id == family,
                AdminSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revocation_reason=reason)
        )

    def begin_totp(self, admin_id: str, *, now: datetime | None = None) -> dict[str, str]:
        now = now or datetime.now(UTC)
        secret = pyotp.random_base32()
        enc = FernetSecretEncryptor(
            self.settings.identity_encryption_key, self.settings.identity_encryption_key_version
        ).encrypt(secret)
        cred = TotpCredentialModel(
            admin_id=admin_id,
            encrypted_secret=enc.ciphertext,
            key_version=enc.key_version,
            created_at=now,
            pending_expires_at=now
            + timedelta(seconds=self.settings.admin_totp_enrollment_lifetime_seconds),
        )
        self.session.add(cred)
        self.session.flush()
        admin = self.session.get(AdminModel, admin_id)
        if admin is None:
            raise ValueError(GENERIC_AUTH_ERROR)
        email = admin.normalized_email
        _event(
            self.session,
            AuditLogModel,
            "admin.mfa.enrollment.started",
            actor_id=admin_id,
            target_id=cred.id,
            now=now,
        )
        return {
            "credential_id": cred.id,
            "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(
                name=email, issuer_name=self.settings.admin_totp_issuer
            ),
        }

    def confirm_totp(
        self, admin_id: str, credential_id: str, code: str, *, now: datetime | None = None
    ) -> list[str]:
        now = now or datetime.now(UTC)
        cred = self.session.get(TotpCredentialModel, credential_id)
        if (
            not cred
            or cred.admin_id != admin_id
            or cred.pending_expires_at is None
            or _cmp(cred.pending_expires_at) < now
        ):
            raise ValueError(GENERIC_AUTH_ERROR)
        enc = FernetSecretEncryptor(
            self.settings.identity_encryption_key, self.settings.identity_encryption_key_version
        )
        secret = enc.decrypt(EncryptedSecret(cred.key_version, cred.encrypted_secret))
        if not pyotp.TOTP(secret).verify(
            code, for_time=now, valid_window=self.settings.admin_totp_clock_window
        ):
            raise ValueError(GENERIC_AUTH_ERROR)
        cred.confirmed_at = now
        codes = [
            "-".join([secrets.token_hex(3), secrets.token_hex(3), secrets.token_hex(3)]).upper()
            for _ in range(self.settings.admin_recovery_code_count)
        ]
        for c in codes:
            self.session.add(
                RecoveryCodeModel(credential_id=cred.id, code_hash=self.tokens.hash(c))
            )
        _event(
            self.session,
            AuditLogModel,
            "admin.mfa.enabled",
            actor_id=admin_id,
            target_id=cred.id,
            now=now,
        )
        return codes

    def validate_csrf(self, session: AdminSessionModel, csrf_token: str | None) -> bool:
        if not csrf_token or not session.csrf_token_hash:
            return False
        return hmac.compare_digest(csrf_token, session.csrf_token_hash)

    def current_profile(self, admin_id: str, session_id: str) -> dict[str, object]:
        admin = self.session.get(AdminModel, admin_id)
        if admin is None:
            raise ValueError(GENERIC_AUTH_ERROR)
        mfa_enabled = (
            self.session.scalar(
                select(TotpCredentialModel).where(
                    TotpCredentialModel.admin_id == admin_id,
                    TotpCredentialModel.revoked_at.is_(None),
                    TotpCredentialModel.confirmed_at.is_not(None),
                )
            )
            is not None
        )
        role_rows = self.session.execute(
            select(RoleModel.machine_name)
            .join(AdminRoleAssignmentModel, AdminRoleAssignmentModel.role_id == RoleModel.id)
            .where(AdminRoleAssignmentModel.admin_id == admin_id)
        ).all()
        return {
            "admin_id": admin.id,
            "email": admin.normalized_email,
            "status": admin.status,
            "mfa_enabled": mfa_enabled,
            "roles": [row[0] for row in role_rows],
            "current_session_id": session_id,
            "password_changed_at": admin.password_changed_at.isoformat()
            if admin.password_changed_at
            else None,
            "last_successful_login_at": admin.last_successful_login_at.isoformat()
            if admin.last_successful_login_at
            else None,
        }

    def list_sessions(self, admin_id: str, current_session_id: str) -> list[dict[str, object]]:
        rows = self.session.scalars(
            select(AdminSessionModel)
            .where(AdminSessionModel.admin_id == admin_id)
            .order_by(AdminSessionModel.created_at.desc())
        ).all()
        return [
            {
                "session_id": row.id,
                "current": row.id == current_session_id,
                "device_label": row.device_label,
                "client": "شناسه مرورگر محفوظ",
                "created_at": row.created_at.isoformat(),
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "idle_expires_at": row.idle_expires_at.isoformat(),
                "absolute_expires_at": row.absolute_expires_at.isoformat(),
                "revoked": row.revoked_at is not None,
            }
            for row in rows
        ]

    def revoke_session(
        self, admin_id: str, session_id: str, *, now: datetime | None = None
    ) -> bool:
        now = now or datetime.now(UTC)
        sess = self.session.get(AdminSessionModel, session_id)
        if sess is None or sess.admin_id != admin_id:
            raise PermissionError(GENERIC_AUTH_ERROR)
        if sess.revoked_at is None:
            sess.revoked_at = now
            sess.revocation_reason = "admin_requested"
            sess.csrf_token_hash = None
            _event(
                self.session,
                AuditLogModel,
                "admin.session.revoked",
                actor_id=admin_id,
                target_id=session_id,
                now=now,
            )
        return True

    def revoke_sessions(
        self,
        admin_id: str,
        *,
        keep_session_id: str | None,
        reason: str,
        now: datetime | None = None,
    ) -> int:
        now = now or datetime.now(UTC)
        rows = self.session.scalars(
            select(AdminSessionModel).where(
                AdminSessionModel.admin_id == admin_id,
                AdminSessionModel.revoked_at.is_(None),
            )
        ).all()
        count = 0
        for row in rows:
            if keep_session_id is not None and row.id == keep_session_id:
                continue
            row.revoked_at = now
            row.revocation_reason = reason
            row.csrf_token_hash = None
            count += 1
        _event(
            self.session,
            AuditLogModel,
            "admin.sessions.revoked_all",
            actor_id=admin_id,
            metadata={"count": count, "mode": "others" if keep_session_id else "all"},
            now=now,
        )
        return count

    def change_password(
        self,
        admin_id: str,
        current_password: str,
        new_password: str,
        current_session_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        admin = self.session.get(AdminModel, admin_id)
        if admin is None or admin.status != AdminStatus.ACTIVE.value:
            raise ValueError(GENERIC_AUTH_ERROR)
        if not self.hasher.verify(current_password, admin.password_hash):
            raise ValueError(GENERIC_AUTH_ERROR)
        if self.hasher.verify(new_password, admin.password_hash):
            raise ValueError(GENERIC_AUTH_ERROR)
        PasswordPolicy(
            self.settings.admin_password_min_length, self.settings.admin_password_max_length
        ).validate(new_password, email=admin.normalized_email)
        admin.password_hash = self.hasher.hash(new_password)
        admin.password_changed_at = now
        self.session.execute(
            update(MfaChallengeModel)
            .where(MfaChallengeModel.admin_id == admin_id, MfaChallengeModel.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        self.revoke_sessions(
            admin_id, keep_session_id=current_session_id, reason="password_changed", now=now
        )
        _event(
            self.session,
            AuditLogModel,
            "admin.password.changed",
            actor_id=admin_id,
            target_id=admin_id,
            now=now,
        )
        _event(
            self.session, SecurityEventModel, "admin.password.changed", actor_id=admin_id, now=now
        )

    def active_totp_credential(self, admin_id: str) -> TotpCredentialModel | None:
        return self.session.scalar(
            select(TotpCredentialModel).where(
                TotpCredentialModel.admin_id == admin_id,
                TotpCredentialModel.revoked_at.is_(None),
                TotpCredentialModel.confirmed_at.is_not(None),
            )
        )

    def regenerate_recovery_codes(
        self, admin_id: str, password: str, proof_code: str, *, now: datetime | None = None
    ) -> list[str]:
        now = now or datetime.now(UTC)
        admin = self.session.get(AdminModel, admin_id)
        cred = self.active_totp_credential(admin_id)
        if admin is None or cred is None or not self.hasher.verify(password, admin.password_hash):
            raise ValueError(GENERIC_AUTH_ERROR)
        if not self._valid_totp_or_recovery(cred, proof_code, now=now):
            raise ValueError(GENERIC_AUTH_ERROR)
        for row in self.session.scalars(
            select(RecoveryCodeModel).where(
                RecoveryCodeModel.credential_id == cred.id, RecoveryCodeModel.used_at.is_(None)
            )
        ).all():
            row.used_at = now
        codes = [
            "-".join([secrets.token_hex(3), secrets.token_hex(3), secrets.token_hex(3)]).upper()
            for _ in range(self.settings.admin_recovery_code_count)
        ]
        for code in codes:
            self.session.add(
                RecoveryCodeModel(credential_id=cred.id, code_hash=self.tokens.hash(code))
            )
        _event(
            self.session,
            AuditLogModel,
            "admin.recovery_codes.regenerated",
            actor_id=admin_id,
            target_id=cred.id,
            now=now,
        )
        _event(
            self.session,
            SecurityEventModel,
            "admin.recovery_codes.regenerated",
            actor_id=admin_id,
            now=now,
        )
        return codes

    def disable_totp(
        self,
        admin_id: str,
        password: str,
        proof_code: str,
        current_session_id: str,
        *,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        admin = self.session.get(AdminModel, admin_id)
        cred = self.active_totp_credential(admin_id)
        if admin is None or cred is None or not self.hasher.verify(password, admin.password_hash):
            raise ValueError(GENERIC_AUTH_ERROR)
        if not self._valid_totp_or_recovery(cred, proof_code, now=now):
            raise ValueError(GENERIC_AUTH_ERROR)
        cred.revoked_at = now
        for row in self.session.scalars(
            select(RecoveryCodeModel).where(
                RecoveryCodeModel.credential_id == cred.id, RecoveryCodeModel.used_at.is_(None)
            )
        ).all():
            row.used_at = now
        self.session.execute(
            update(MfaChallengeModel)
            .where(MfaChallengeModel.admin_id == admin_id, MfaChallengeModel.consumed_at.is_(None))
            .values(consumed_at=now)
        )
        self.revoke_sessions(
            admin_id, keep_session_id=current_session_id, reason="mfa_disabled", now=now
        )
        _event(
            self.session,
            AuditLogModel,
            "admin.mfa.disabled",
            actor_id=admin_id,
            target_id=cred.id,
            now=now,
        )
        _event(self.session, SecurityEventModel, "admin.mfa.disabled", actor_id=admin_id, now=now)
