from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from vpnsale_domain.identity import normalize_account_username

from platform_api.admin_auth.rate_limit import (
    InMemoryRateLimiter,
    RateLimiter,
    RateLimitUnavailable,
    RedisRateLimiter,
)
from platform_api.admin_auth.service import hardened_rate_key
from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import (
    AccountCredentialModel,
    CustomerSessionModel,
    TelegramAccountModel,
    UserModel,
)

from .service import (
    GENERIC_REGISTRATION_CONFLICT,
    CustomerAuthService,
    CustomerAuthStateChangedError,
)
from .telegram import TelegramInitDataError

router = APIRouter(prefix="/api/v1/customer/auth", tags=["customer-auth"])
registration_router = APIRouter(prefix="/api/v1/customer/auth", tags=["customer-auth"])
password_login_router = APIRouter(prefix="/api/v1/customer/auth", tags=["customer-auth"])


class ApiError(BaseModel):
    code: str
    message_key: str
    correlation_id: str


class TelegramLoginRequest(BaseModel):
    init_data: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str | None = None
    csrf_token: str | None = None
    session_id: str | None = None


class AuthCapabilitiesResponse(BaseModel):
    password_login: bool
    public_registration: bool
    telegram_login: bool
    email_recovery: bool = False
    telegram_recovery: bool = False
    recovery_codes: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class OkResponse(BaseModel):
    ok: bool = True


class ProfileResponse(BaseModel):
    customer_id: str
    account_status: str
    telegram_user_id: int | None
    username: str | None
    account_username: str | None
    first_name: str | None
    last_name: str | None
    language_code: str | None
    created_at: str
    last_seen_at: str | None
    current_session_id: str


class SessionResponse(BaseModel):
    session_id: str
    current: bool
    device_label: str | None
    created_at: str
    last_used_at: str | None
    idle_expires_at: str
    absolute_expires_at: str
    revoked: bool


@lru_cache
def get_customer_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.environment.lower() in {"production", "prod", "staging"}:
        return RedisRateLimiter(settings)
    return InMemoryRateLimiter(settings)


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _err(code: int, request: Request, headers: dict[str, str] | None = None) -> HTTPException:
    return HTTPException(
        code,
        detail=ApiError(
            code="customer_auth_failed",
            message_key="customer.auth.generic_failure",
            correlation_id=_cid(request),
        ).model_dump(),
        headers=headers,
    )


def _registration_err(code: int, request: Request, message_key: str) -> HTTPException:
    return HTTPException(
        code,
        detail=ApiError(
            code="customer_registration_failed",
            message_key=message_key,
            correlation_id=_cid(request),
        ).model_dump(),
    )


def _svc(db: Session, settings: Settings) -> CustomerAuthService:
    return CustomerAuthService(db, settings)


def _persist_auth_failure(db: Session, exc: CustomerAuthStateChangedError) -> None:
    """Persist only service failures explicitly declaring intentional security state."""
    db.commit()


def _set_cookie(response: Response, settings: Settings, refresh: str) -> None:
    response.set_cookie(
        settings.customer_refresh_cookie_name,
        refresh,
        httponly=True,
        secure=settings.customer_refresh_cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.customer_refresh_cookie_samesite),
        path=settings.customer_refresh_cookie_path,
        domain=settings.customer_refresh_cookie_domain or None,
        max_age=settings.customer_session_absolute_lifetime_seconds,
    )


def _clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.customer_refresh_cookie_name,
        path=settings.customer_refresh_cookie_path,
        domain=settings.customer_refresh_cookie_domain or None,
        secure=settings.customer_refresh_cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.customer_refresh_cookie_samesite),
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def browser_request_guard(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_vpn_sale_client: Annotated[str | None, Header()] = None,
) -> None:
    """Reject ambient-cookie bootstrap requests before DB/Redis dependencies run."""
    origin = request.headers.get("origin")
    allowed_origin = _normalized_web_origin(settings.public_app_origin)
    fetch_site = request.headers.get("sec-fetch-site")
    if (
        allowed_origin is None
        or _normalized_web_origin(origin) != allowed_origin
        or x_vpn_sale_client != "customer-web"
        or fetch_site == "cross-site"
        or (fetch_site is not None and fetch_site not in {"same-origin", "same-site", "none"})
    ):
        raise _err(403, request)


def _normalized_web_origin(value: str | None) -> tuple[str, str, int | None] | None:
    """Return a strict browser Origin tuple, never a general URL."""
    if not value or value == "null":
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    if parsed.path == "/" and not value.endswith("/"):
        return None
    normalized_port = port
    if (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80):
        normalized_port = None
    return parsed.scheme, parsed.hostname.lower(), normalized_port


@router.get("/capabilities", response_model=AuthCapabilitiesResponse)
def capabilities(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> AuthCapabilitiesResponse:
    _no_store(response)
    return AuthCapabilitiesResponse(
        password_login=settings.password_account_login_enabled,
        public_registration=settings.public_account_registration_enabled,
        telegram_login=settings.telegram_customer_auth_enabled,
    )


@router.post("/browser-bootstrap", response_model=AuthResponse)
async def browser_bootstrap(
    request: Request,
    response: Response,
    _: Annotated[None, Depends(browser_request_guard)],
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_customer_rate_limiter)],
) -> AuthResponse:
    _no_store(response)
    presented = request.cookies.get(settings.customer_refresh_cookie_name)
    if not presented:
        raise _err(401, request)
    await _rate(
        limiter,
        request,
        "customer-browser-bootstrap",
        hardened_rate_key(
            "ip",
            request.client.host if request.client else "",
            salt=settings.opaque_token_hash_salt,
        ),
        limit=settings.customer_refresh_rate_limit,
        window_seconds=settings.customer_refresh_rate_limit_window_seconds,
    )
    try:
        result = _svc(db, settings).refresh(presented)
    except CustomerAuthStateChangedError as exc:
        _persist_auth_failure(db, exc)
        raise _err(401, request) from exc
    except ValueError as exc:
        raise _err(401, request) from exc
    _set_cookie(response, settings, result.refresh_token)
    return AuthResponse(
        access_token=result.access_token,
        csrf_token=result.csrf_token,
        session_id=result.session_id,
    )


async def _rate(
    limiter: RateLimiter,
    request: Request,
    purpose: str,
    *parts: str,
    limit: int,
    window_seconds: int,
) -> None:
    try:
        res = await limiter.check(purpose, *parts, limit=limit, window_seconds=window_seconds)
    except RateLimitUnavailable as exc:
        raise _err(503, request) from exc
    if not res.allowed:
        raise _err(429, request, {"Retry-After": str(res.retry_after)})


def _current(
    auth: str | None, db: Session, settings: Settings, request: Request
) -> CustomerSessionModel:
    if not auth or not auth.lower().startswith("bearer "):
        raise _err(401, request)
    try:
        claims = _svc(db, settings).access.validate(auth.split(" ", 1)[1])
    except ValueError as exc:
        raise _err(401, request) from exc
    sess = db.get(CustomerSessionModel, claims["session_id"])
    user = db.get(UserModel, claims["user_id"])
    now = datetime.now(UTC)
    if (
        not sess
        or not user
        or sess.revoked_at
        or sess.consumed_at
        or user.status != "ACTIVE"
        or sess.idle_expires_at.replace(tzinfo=UTC) < now
        or sess.absolute_expires_at.replace(tzinfo=UTC) < now
    ):
        raise _err(401, request)
    return sess


def current_customer_session_dependency(
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> CustomerSessionModel:
    return _current(authorization, db, settings, request)


@router.post("/telegram-mini-app", response_model=AuthResponse)
async def telegram_login(
    body: TelegramLoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_customer_rate_limiter)],
) -> AuthResponse:
    await _rate(
        limiter,
        request,
        "customer-telegram-auth",
        hardened_rate_key(
            "ip",
            request.client.host if request.client else "",
            salt=settings.opaque_token_hash_salt,
        ),
        limit=settings.customer_login_rate_limit,
        window_seconds=settings.customer_login_rate_limit_window_seconds,
    )
    try:
        result = _svc(db, settings).authenticate_telegram(
            body.init_data,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
    except CustomerAuthStateChangedError as exc:
        _persist_auth_failure(db, exc)
        raise _err(401, request) from exc
    except (ValueError, TelegramInitDataError) as exc:
        raise _err(401, request) from exc
    _set_cookie(response, settings, result.refresh_token)
    return AuthResponse(
        access_token=result.access_token, csrf_token=result.csrf_token, session_id=result.session_id
    )


@registration_router.post("/register", response_model=AuthResponse)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_customer_rate_limiter)],
) -> AuthResponse:
    ip_key = hardened_rate_key(
        "ip", request.client.host if request.client else "", salt=settings.opaque_token_hash_salt
    )
    await _rate(
        limiter,
        request,
        "customer-registration-global",
        "global",
        limit=settings.customer_registration_global_rate_limit,
        window_seconds=settings.customer_login_rate_limit_window_seconds,
    )
    await _rate(
        limiter,
        request,
        "customer-registration-ip",
        ip_key,
        limit=settings.customer_registration_rate_limit,
        window_seconds=settings.customer_login_rate_limit_window_seconds,
    )
    try:
        normalized = normalize_account_username(body.username)
    except ValueError:
        normalized = ""
    if normalized:
        await _rate(
            limiter,
            request,
            "customer-registration-username",
            hardened_rate_key("username", normalized, salt=settings.opaque_token_hash_salt),
            limit=settings.customer_registration_rate_limit,
            window_seconds=settings.customer_login_rate_limit_window_seconds,
        )
    try:
        result = _svc(db, settings).register_password_account(
            body.username,
            body.password,
            email=body.email,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
            correlation_id=_cid(request),
        )
    except CustomerAuthStateChangedError as exc:
        _persist_auth_failure(db, exc)
        if str(exc) == GENERIC_REGISTRATION_CONFLICT:
            raise _registration_err(409, request, "customer.registration.conflict") from exc
        raise _registration_err(422, request, "customer.registration.validation_failed") from exc
    except ValueError as exc:
        if str(exc) == GENERIC_REGISTRATION_CONFLICT:
            raise _registration_err(409, request, "customer.registration.conflict") from exc
        raise _registration_err(422, request, "customer.registration.validation_failed") from exc
    _set_cookie(response, settings, result.refresh_token)
    return AuthResponse(
        access_token=result.access_token, csrf_token=result.csrf_token, session_id=result.session_id
    )


@password_login_router.post("/password-login", response_model=AuthResponse)
async def password_login(
    body: PasswordLoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_customer_rate_limiter)],
) -> AuthResponse:
    try:
        normalized = normalize_account_username(body.username)
    except ValueError as exc:
        raise _err(401, request) from exc
    for purpose, key in (
        (
            "customer-password-login-ip",
            hardened_rate_key(
                "ip",
                request.client.host if request.client else "",
                salt=settings.opaque_token_hash_salt,
            ),
        ),
        (
            "customer-password-login-username",
            hardened_rate_key("username", normalized, salt=settings.opaque_token_hash_salt),
        ),
    ):
        await _rate(
            limiter,
            request,
            purpose,
            key,
            limit=settings.customer_password_login_rate_limit,
            window_seconds=settings.customer_login_rate_limit_window_seconds,
        )
    try:
        result = _svc(db, settings).authenticate_password(
            body.username,
            body.password,
            ip=request.client.host if request.client else "",
            user_agent=request.headers.get("user-agent", ""),
        )
    except CustomerAuthStateChangedError as exc:
        _persist_auth_failure(db, exc)
        raise _err(401, request) from exc
    except ValueError as exc:
        raise _err(401, request) from exc
    _set_cookie(response, settings, result.refresh_token)
    return AuthResponse(
        access_token=result.access_token, csrf_token=result.csrf_token, session_id=result.session_id
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_customer_rate_limiter)],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    presented = body.refresh_token or request.cookies.get(settings.customer_refresh_cookie_name)
    if not presented:
        raise _err(401, request)
    svc = _svc(db, settings)
    sess = svc.session_for_refresh(presented)
    if not sess or not svc.validate_csrf(sess, x_csrf_token):
        raise _err(403, request)
    await _rate(
        limiter,
        request,
        "customer-refresh",
        sess.id,
        limit=settings.customer_refresh_rate_limit,
        window_seconds=settings.customer_refresh_rate_limit_window_seconds,
    )
    try:
        result = svc.refresh(presented)
    except CustomerAuthStateChangedError as exc:
        _persist_auth_failure(db, exc)
        raise _err(401, request) from exc
    except ValueError as exc:
        raise _err(401, request) from exc
    _set_cookie(response, settings, result.refresh_token)
    return AuthResponse(
        access_token=result.access_token, csrf_token=result.csrf_token, session_id=result.session_id
    )


@router.get("/me", response_model=ProfileResponse)
def me(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> ProfileResponse:
    sess = _current(authorization, db, settings, request)
    user = db.get(UserModel, sess.user_id)
    tg = db.scalar(select(TelegramAccountModel).where(TelegramAccountModel.user_id == sess.user_id))
    credential = db.get(AccountCredentialModel, sess.user_id)
    assert user
    return ProfileResponse(
        customer_id=user.id,
        account_status=user.status,
        telegram_user_id=tg.telegram_user_id if tg else None,
        username=tg.username if tg else None,
        account_username=credential.username if credential else None,
        first_name=tg.first_name if tg else None,
        last_name=tg.last_name if tg else None,
        language_code=tg.language_code if tg else None,
        created_at=user.created_at.isoformat(),
        last_seen_at=tg.last_seen_at.isoformat() if tg else None,
        current_session_id=sess.id,
    )


@router.get("/sessions", response_model=list[SessionResponse])
def sessions(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> list[SessionResponse]:
    cur = _current(authorization, db, settings, request)
    rows = db.scalars(
        select(CustomerSessionModel)
        .where(CustomerSessionModel.user_id == cur.user_id)
        .order_by(CustomerSessionModel.created_at.desc())
    ).all()
    return [
        SessionResponse(
            session_id=s.id,
            current=s.id == cur.id,
            device_label=s.device_label,
            created_at=s.created_at.isoformat(),
            last_used_at=s.last_used_at.isoformat() if s.last_used_at else None,
            idle_expires_at=s.idle_expires_at.isoformat(),
            absolute_expires_at=s.absolute_expires_at.isoformat(),
            revoked=bool(s.revoked_at),
        )
        for s in rows
    ]


def _require_csrf(
    svc: CustomerAuthService, sess: CustomerSessionModel, token: str | None, request: Request
) -> None:
    if not svc.validate_csrf(sess, token):
        raise _err(403, request)


def _revoke(db: Session, user_id: str, session_id: str, now: datetime, reason: str) -> bool:
    row = db.get(CustomerSessionModel, session_id)
    if not row or row.user_id != user_id:
        return False
    if not row.revoked_at:
        row.revoked_at = now
        row.revocation_reason = reason
    return True


@router.post("/logout", response_model=OkResponse)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    cur = _current(authorization, db, settings, request)
    svc = _svc(db, settings)
    _require_csrf(svc, cur, x_csrf_token, request)
    cur.revoked_at = datetime.now(UTC)
    cur.revocation_reason = "customer_logout"
    _clear_cookie(response, settings)
    return OkResponse()


@router.delete("/sessions/{session_id}", response_model=OkResponse)
def revoke_one(
    session_id: str,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    cur = _current(authorization, db, settings, request)
    svc = _svc(db, settings)
    _require_csrf(svc, cur, x_csrf_token, request)
    if not _revoke(db, cur.user_id, session_id, datetime.now(UTC), "customer_revoked"):
        raise _err(404, request)
    if session_id == cur.id:
        _clear_cookie(response, settings)
    return OkResponse()


@router.post("/sessions/revoke-others", response_model=OkResponse)
def revoke_others(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    cur = _current(authorization, db, settings, request)
    svc = _svc(db, settings)
    _require_csrf(svc, cur, x_csrf_token, request)
    db.execute(
        update(CustomerSessionModel)
        .where(
            CustomerSessionModel.user_id == cur.user_id,
            CustomerSessionModel.id != cur.id,
            CustomerSessionModel.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC), revocation_reason="customer_revoked_others")
    )
    return OkResponse()


@router.post("/sessions/revoke-all", response_model=OkResponse)
def revoke_all(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    cur = _current(authorization, db, settings, request)
    svc = _svc(db, settings)
    _require_csrf(svc, cur, x_csrf_token, request)
    db.execute(
        update(CustomerSessionModel)
        .where(
            CustomerSessionModel.user_id == cur.user_id, CustomerSessionModel.revoked_at.is_(None)
        )
        .values(revoked_at=datetime.now(UTC), revocation_reason="customer_revoked_all")
    )
    _clear_cookie(response, settings)
    return OkResponse()


@router.get("/csrf", response_model=AuthResponse)
def csrf(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> AuthResponse:
    cur = _current(authorization, db, settings, request)
    svc = _svc(db, settings)
    token = svc.tokens.generate()
    cur.csrf_token_hash = svc.tokens.hash(token)
    return AuthResponse(csrf_token=token, session_id=cur.id)
