from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.identity import (
    UserStatus,
    normalize_account_email,
    normalize_account_username,
    sanitize_metadata,
    validate_customer_password,
)

from platform_api.config import Settings
from platform_api.identity.models import (
    AccountCredentialModel,
    AccountEmailModel,
    AuditLogModel,
    CustomerProfileModel,
    CustomerSessionModel,
    RoleModel,
    SecurityEventModel,
    TelegramAccountModel,
    UserModel,
    UserRoleAssignmentModel,
)
from platform_api.identity.security import Argon2idPasswordHasher, OpaqueTokenService

from .telegram import TelegramInitData, TelegramInitDataVerifier

GENERIC_CUSTOMER_AUTH_ERROR = "Invalid credentials or authentication state"
GENERIC_REGISTRATION_CONFLICT = "Account registration could not be completed"


def _cmp(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


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
                actor_type="customer" if actor_id else "system",
                actor_id=actor_id,
                target_type="customer",
                target_id=target_id,
                event_code=code,
                occurred_at=now,
                metadata_=safe,
            )
        )
    else:
        session.add(
            SecurityEventModel(
                actor_type="customer" if actor_id else "system",
                actor_id=actor_id,
                event_code=code,
                occurred_at=now,
                metadata_=safe,
            )
        )


class CustomerAccessTokenService:
    algorithm = "HS256"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def issue(self, *, user_id: str, session_id: str, now: datetime) -> str:
        exp = now + timedelta(seconds=self.settings.customer_access_token_lifetime_seconds)
        return jwt.encode(
            {
                "iss": self.settings.customer_access_token_issuer,
                "aud": self.settings.customer_access_token_audience,
                "sub": user_id,
                "sid": session_id,
                "iat": int(now.timestamp()),
                "exp": int(exp.timestamp()),
                "jti": str(uuid4()),
            },
            self.settings.customer_access_token_signing_key,
            algorithm=self.algorithm,
            headers={"kid": self.settings.customer_access_token_key_id},
        )

    def validate(self, token: str) -> dict[str, str]:
        try:
            claims = jwt.decode(
                token,
                self.settings.customer_access_token_signing_key,
                algorithms=[self.algorithm],
                issuer=self.settings.customer_access_token_issuer,
                audience=self.settings.customer_access_token_audience,
                leeway=self.settings.customer_access_token_clock_skew_seconds,
            )
        except jwt.PyJWTError as exc:
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR) from exc
        return {
            "user_id": str(claims["sub"]),
            "session_id": str(claims["sid"]),
            "jti": str(claims["jti"]),
        }


@dataclass(frozen=True, slots=True)
class CustomerAuthResult:
    access_token: str
    refresh_token: str
    csrf_token: str
    session_id: str
    user_id: str


class CustomerAuthService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.tokens = OpaqueTokenService(
            settings.opaque_token_bytes, settings.opaque_token_hash_salt
        )
        self.access = CustomerAccessTokenService(settings)
        self.passwords = Argon2idPasswordHasher(
            time_cost=settings.password_argon2_time_cost,
            memory_cost=settings.password_argon2_memory_cost,
            parallelism=settings.password_argon2_parallelism,
        )
        self.verifier = (
            TelegramInitDataVerifier(
                bot_token=settings.telegram_bot_token,
                max_age_seconds=settings.telegram_init_data_max_age_seconds,
                future_skew_seconds=settings.telegram_init_data_future_skew_seconds,
                max_length=settings.telegram_init_data_max_length,
            )
            if settings.telegram_bot_token
            else None
        )

    def authenticate_telegram(
        self, raw_init_data: str, *, now: datetime | None = None, ip: str = "", user_agent: str = ""
    ) -> CustomerAuthResult:
        now = now or datetime.now(UTC)
        if self.verifier is None:
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        verified = self.verifier.verify(raw_init_data, now=now)
        user = self._link_identity(verified, now=now)
        if user.status == UserStatus.PENDING.value:
            user.status = UserStatus.ACTIVE.value
            user.updated_at = now
        if user.status != UserStatus.ACTIVE.value:
            _event(
                self.session,
                SecurityEventModel,
                "customer.authentication.blocked_by_status",
                actor_id=user.id,
                metadata={"reason": "status"},
                now=now,
            )
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        result = self.issue_session(
            user, now=now, ip=ip, user_agent=user_agent, device_label="Telegram Mini App"
        )
        _event(
            self.session, SecurityEventModel, "customer.login.succeeded", actor_id=user.id, now=now
        )
        return result

    def _link_identity(self, verified: TelegramInitData, *, now: datetime) -> UserModel:
        tg = self.session.scalar(
            select(TelegramAccountModel).where(
                TelegramAccountModel.telegram_user_id == verified.user.telegram_user_id
            )
        )
        if tg and tg.user_id:
            user = self.session.get(UserModel, tg.user_id)
            if user is None:
                raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        else:
            user = UserModel(status=UserStatus.PENDING.value, created_at=now, updated_at=now)
            self.session.add(user)
            self.session.flush()
            self.session.add(
                CustomerProfileModel(
                    user_id=user.id,
                    display_name=verified.user.first_name,
                    locale=verified.user.language_code,
                )
            )
            tg = TelegramAccountModel(
                telegram_user_id=verified.user.telegram_user_id,
                user_id=user.id,
                first_seen_at=now,
                last_seen_at=now,
            )
            self.session.add(tg)
            self._assign_customer_role(user.id, now=now)
            try:
                self.session.flush()
            except IntegrityError:
                self.session.rollback()
                tg = self.session.scalar(
                    select(TelegramAccountModel).where(
                        TelegramAccountModel.telegram_user_id == verified.user.telegram_user_id
                    )
                )
                if not tg or not tg.user_id:
                    raise
                user = self.session.get(UserModel, tg.user_id)
                if user is None:
                    raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR) from None
            _event(
                self.session,
                AuditLogModel,
                "customer.registered",
                actor_id=user.id,
                target_id=user.id,
                now=now,
            )
            _event(
                self.session,
                AuditLogModel,
                "customer.telegram_identity.created",
                actor_id=user.id,
                target_id=tg.id,
                now=now,
            )
        changed = (
            tg.username,
            tg.first_name,
            tg.last_name,
            tg.language_code,
            tg.photo_url,
            tg.start_attribution,
        ) != (
            verified.user.username,
            verified.user.first_name,
            verified.user.last_name,
            verified.user.language_code,
            verified.user.photo_url,
            verified.start_param,
        )
        tg.username = verified.user.username
        tg.first_name = verified.user.first_name
        tg.last_name = verified.user.last_name
        tg.language_code = verified.user.language_code
        tg.photo_url = verified.user.photo_url
        tg.start_attribution = verified.start_param
        tg.last_seen_at = now
        if changed:
            _event(
                self.session,
                AuditLogModel,
                "customer.telegram_identity.updated",
                actor_id=user.id,
                target_id=tg.id,
                now=now,
            )
        return user

    def _assign_customer_role(self, user_id: str, *, now: datetime) -> None:
        role = self.session.scalar(select(RoleModel).where(RoleModel.machine_name == "customer"))
        if role is None:
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        existing = self.session.get(UserRoleAssignmentModel, (user_id, role.id))
        if existing is None:
            self.session.add(
                UserRoleAssignmentModel(user_id=user_id, role_id=role.id, assigned_at=now)
            )

    def issue_session(
        self,
        user: UserModel,
        *,
        now: datetime,
        ip: str = "",
        user_agent: str = "",
        device_label: str,
    ) -> CustomerAuthResult:
        raw = self.tokens.generate()
        sid = str(uuid4())
        fam = str(uuid4())
        sess = CustomerSessionModel(
            id=sid,
            user_id=user.id,
            refresh_token_hash=self.tokens.hash(raw),
            session_family_id=fam,
            rotation_sequence=0,
            created_at=now,
            last_used_at=now,
            idle_expires_at=now
            + timedelta(seconds=self.settings.customer_session_idle_timeout_seconds),
            absolute_expires_at=now
            + timedelta(seconds=self.settings.customer_session_absolute_lifetime_seconds),
            ip_metadata={"present": bool(ip)},
            user_agent_metadata={"present": bool(user_agent)},
            device_label=device_label,
        )
        csrf_token = self.csrf_for(sid)
        sess.csrf_token_hash = csrf_token
        self.session.add(sess)
        _event(
            self.session,
            AuditLogModel,
            "customer.session.created",
            actor_id=user.id,
            target_id=sid,
            now=now,
        )
        return CustomerAuthResult(
            self.access.issue(user_id=user.id, session_id=sid, now=now),
            raw,
            csrf_token,
            sid,
            user.id,
        )

    def register_password_account(
        self,
        username: str,
        password: str,
        *,
        email: str | None,
        now: datetime | None = None,
        ip: str = "",
        user_agent: str = "",
        correlation_id: str = "",
    ) -> CustomerAuthResult:
        now = now or datetime.now(UTC)
        normalized_username = normalize_account_username(username)
        normalized_email = normalize_account_email(email) if email is not None else None
        validate_customer_password(
            password,
            normalized_username,
            min_length=self.settings.customer_password_min_length,
            max_length=self.settings.customer_password_max_length,
        )
        try:
            with self.session.begin_nested():
                user = UserModel(status=UserStatus.ACTIVE.value, created_at=now, updated_at=now)
                self.session.add(user)
                self.session.flush()
                self.session.add(CustomerProfileModel(user_id=user.id))
                self.session.add(
                    AccountCredentialModel(
                        user_id=user.id,
                        username=username,
                        normalized_username=normalized_username,
                        password_hash=self.passwords.hash(password),
                        password_changed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                if normalized_email is not None:
                    self.session.add(
                        AccountEmailModel(
                            user_id=user.id,
                            normalized_email=normalized_email,
                            verified_at=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                self._assign_customer_role(user.id, now=now)
                result = self.issue_session(
                    user,
                    now=now,
                    ip=ip,
                    user_agent=user_agent,
                    device_label="Web browser",
                )
                for model in (AuditLogModel, SecurityEventModel):
                    _event(
                        self.session,
                        model,
                        "customer.registration.succeeded",
                        actor_id=user.id,
                        target_id=user.id,
                        metadata={
                            "method": "password",
                            "email_supplied": email is not None,
                            "ip_present": bool(ip),
                            "user_agent_present": bool(user_agent),
                            "correlation_present": bool(correlation_id),
                        },
                        now=now,
                    )
                self.session.flush()
                return result
        except IntegrityError as exc:
            _event(
                self.session,
                SecurityEventModel,
                "customer.registration.conflict",
                metadata={"method": "password", "reason": "conflict"},
                now=now,
            )
            raise ValueError(GENERIC_REGISTRATION_CONFLICT) from exc

    def authenticate_password(
        self,
        username: str,
        password: str,
        *,
        now: datetime | None = None,
        ip: str = "",
        user_agent: str = "",
    ) -> CustomerAuthResult:
        now = now or datetime.now(UTC)
        normalized = normalize_account_username(username)
        credential = self.session.scalar(
            select(AccountCredentialModel)
            .where(AccountCredentialModel.normalized_username == normalized)
            .with_for_update()
        )
        # Compute on every password-login attempt so neither known nor unknown users get a
        # shortcut, while unrelated Telegram/refresh paths do no password work.
        dummy_hash = self.passwords.hash("dummy-" + "authentication-passphrase")
        supplied_hash = credential.password_hash if credential else dummy_hash
        verified = self.passwords.verify(password, supplied_hash)
        user = self.session.get(UserModel, credential.user_id) if credential else None
        locked = bool(credential and credential.lock_until and _cmp(credential.lock_until) > now)
        if (
            not credential
            or not user
            or user.status != UserStatus.ACTIVE.value
            or locked
            or not verified
        ):
            if credential and not locked:
                credential.failed_login_count += 1
                credential.last_failed_login_at = now
                credential.updated_at = now
                if (
                    credential.failed_login_count
                    >= self.settings.customer_password_lockout_threshold
                ):
                    credential.lock_until = now + timedelta(
                        seconds=self.settings.customer_password_lockout_duration_seconds
                    )
                    code = "customer.password_login.locked"
                else:
                    code = "customer.password_login.failed"
                _event(
                    self.session,
                    SecurityEventModel,
                    code,
                    actor_id=credential.user_id,
                    metadata={"method": "password", "reason": "authentication_failed"},
                    now=now,
                )
            else:
                _event(
                    self.session,
                    SecurityEventModel,
                    "customer.password_login.failed",
                    metadata={"method": "password", "reason": "authentication_failed"},
                    now=now,
                )
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        credential.failed_login_count = 0
        credential.lock_until = None
        credential.last_successful_login_at = now
        credential.updated_at = now
        if self.passwords.needs_rehash(credential.password_hash):
            credential.password_hash = self.passwords.hash(password)
            _event(
                self.session,
                SecurityEventModel,
                "customer.password_hash.rehashed",
                actor_id=user.id,
                metadata={"method": "password"},
                now=now,
            )
        result = self.issue_session(
            user, now=now, ip=ip, user_agent=user_agent, device_label="Web browser"
        )
        for model in (AuditLogModel, SecurityEventModel):
            _event(
                self.session,
                model,
                "customer.password_login.succeeded",
                actor_id=user.id,
                target_id=user.id,
                metadata={"method": "password"},
                now=now,
            )
        return result

    def csrf_for(self, session_id: str) -> str:
        return self.tokens.hash(f"customer-csrf:{session_id}:{self.settings.customer_csrf_secret}")

    def validate_csrf(self, sess: CustomerSessionModel, token: str | None) -> bool:
        return bool(
            token and sess.csrf_token_hash and self.tokens.verify(token, sess.csrf_token_hash)
        )

    def session_for_refresh(self, refresh_token: str) -> CustomerSessionModel | None:
        return self.session.scalar(
            select(CustomerSessionModel).where(
                CustomerSessionModel.refresh_token_hash == self.tokens.hash(refresh_token)
            )
        )

    def refresh(self, refresh_token: str, *, now: datetime | None = None) -> CustomerAuthResult:
        now = now or datetime.now(UTC)
        h = self.tokens.hash(refresh_token)
        sess = self.session.scalar(
            select(CustomerSessionModel).where(CustomerSessionModel.refresh_token_hash == h)
        )
        if not sess:
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        if sess.consumed_at is not None:
            self._revoke_family(sess.session_family_id, now, "refresh_reuse")
            sess.reuse_detected_at = now
            _event(
                self.session,
                AuditLogModel,
                "customer.refresh_reuse_detected",
                actor_id=sess.user_id,
                target_id=sess.id,
                now=now,
            )
            _event(
                self.session,
                SecurityEventModel,
                "customer.refresh_reuse_detected",
                actor_id=sess.user_id,
                now=now,
            )
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        if (
            sess.revoked_at
            or _cmp(sess.idle_expires_at) < now
            or _cmp(sess.absolute_expires_at) < now
        ):
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        user = self.session.get(UserModel, sess.user_id)
        if not user or user.status != UserStatus.ACTIVE.value:
            raise ValueError(GENERIC_CUSTOMER_AUTH_ERROR)
        sess.consumed_at = now
        raw = self.tokens.generate()
        nxt = CustomerSessionModel(
            user_id=sess.user_id,
            refresh_token_hash=self.tokens.hash(raw),
            session_family_id=sess.session_family_id,
            parent_session_id=sess.id,
            rotation_sequence=sess.rotation_sequence + 1,
            created_at=now,
            last_used_at=now,
            idle_expires_at=now
            + timedelta(seconds=self.settings.customer_session_idle_timeout_seconds),
            absolute_expires_at=sess.absolute_expires_at,
            ip_metadata=sess.ip_metadata,
            user_agent_metadata=sess.user_agent_metadata,
            device_label=sess.device_label,
        )
        self.session.add(nxt)
        self.session.flush()
        csrf_token = self.csrf_for(nxt.id)
        nxt.csrf_token_hash = csrf_token
        _event(
            self.session,
            AuditLogModel,
            "customer.session.refreshed",
            actor_id=sess.user_id,
            target_id=nxt.id,
            now=now,
        )
        return CustomerAuthResult(
            self.access.issue(user_id=sess.user_id, session_id=nxt.id, now=now),
            raw,
            csrf_token,
            nxt.id,
            sess.user_id,
        )

    def _revoke_family(self, family: str, now: datetime, reason: str) -> None:
        self.session.execute(
            update(CustomerSessionModel)
            .where(
                CustomerSessionModel.session_family_id == family,
                CustomerSessionModel.revoked_at.is_(None),
            )
            .values(revoked_at=now, revocation_reason=reason)
        )
