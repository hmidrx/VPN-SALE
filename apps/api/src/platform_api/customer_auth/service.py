from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.identity import UserStatus, sanitize_metadata

from platform_api.config import Settings
from platform_api.identity.models import (
    AuditLogModel,
    CustomerProfileModel,
    CustomerSessionModel,
    SecurityEventModel,
    TelegramAccountModel,
    UserModel,
)
from platform_api.identity.security import OpaqueTokenService

from .telegram import TelegramInitData, TelegramInitDataVerifier

GENERIC_CUSTOMER_AUTH_ERROR = "Invalid credentials or authentication state"


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
        self.verifier = TelegramInitDataVerifier(
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_init_data_max_age_seconds,
            future_skew_seconds=settings.telegram_init_data_future_skew_seconds,
            max_length=settings.telegram_init_data_max_length,
        )

    def authenticate_telegram(
        self, raw_init_data: str, *, now: datetime | None = None, ip: str = "", user_agent: str = ""
    ) -> CustomerAuthResult:
        now = now or datetime.now(UTC)
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
        result = self._create_session(user, now=now, ip=ip, user_agent=user_agent)
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

    def _create_session(
        self, user: UserModel, *, now: datetime, ip: str = "", user_agent: str = ""
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
            device_label="Telegram Mini App",
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
