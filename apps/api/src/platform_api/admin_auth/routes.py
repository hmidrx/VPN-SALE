from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel, AdminSessionModel
from platform_api.identity.security import Argon2idPasswordHasher

from .rate_limit import InMemoryRateLimiter, RateLimiter, RateLimitUnavailable, RedisRateLimiter
from .service import AdminAuthService, AuthenticationOutcome

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])


class ApiError(BaseModel):
    code: str
    message_key: str
    correlation_id: str


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    outcome: AuthenticationOutcome
    access_token: str | None = None
    csrf_token: str | None = None
    mfa_challenge: str | None = None


class MfaVerifyRequest(BaseModel):
    challenge: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class TotpConfirmRequest(BaseModel):
    credential_id: str
    code: str


class StrongConfirmationRequest(BaseModel):
    current_password: str
    code: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=1, max_length=1024)


class ProfileResponse(BaseModel):
    admin_id: str
    email: str
    status: str
    mfa_enabled: bool
    roles: list[str]
    current_session_id: str
    password_changed_at: str | None
    last_successful_login_at: str | None


class SessionResponse(BaseModel):
    session_id: str
    current: bool
    device_label: str | None
    client: str
    created_at: str
    last_used_at: str | None
    idle_expires_at: str
    absolute_expires_at: str
    revoked: bool


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class TotpBeginResponse(BaseModel):
    credential_id: str
    otpauth_uri: str


class OkResponse(BaseModel):
    ok: bool = True


@lru_cache
def get_rate_limiter() -> RateLimiter:
    settings = get_settings()
    if settings.environment.lower() in {"production", "prod", "staging"}:
        return RedisRateLimiter(settings)
    return InMemoryRateLimiter(settings)


def _service(db: Session, settings: Settings) -> AdminAuthService:
    hasher = Argon2idPasswordHasher(
        settings.password_argon2_time_cost,
        settings.password_argon2_memory_cost,
        settings.password_argon2_parallelism,
    )
    return AdminAuthService(db, settings, hasher)


def _correlation_id(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _generic_http(
    status_code: int, request: Request, headers: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(
        status_code,
        detail=ApiError(
            code="admin_auth_failed",
            message_key="admin.auth.generic_failure",
            correlation_id=_correlation_id(request),
        ).model_dump(),
        headers=headers,
    )


def _set_cookie(response: Response, settings: Settings, refresh: str) -> None:
    response.set_cookie(
        settings.admin_refresh_cookie_name,
        refresh,
        httponly=True,
        secure=settings.admin_refresh_cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.admin_refresh_cookie_samesite),
        path=settings.admin_refresh_cookie_path,
        domain=settings.admin_refresh_cookie_domain or None,
        max_age=settings.admin_session_absolute_lifetime_seconds,
    )


def _clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.admin_refresh_cookie_name,
        path=settings.admin_refresh_cookie_path,
        domain=settings.admin_refresh_cookie_domain or None,
        secure=settings.admin_refresh_cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.admin_refresh_cookie_samesite),
    )


def _current(
    authorization: str | None, db: Session, settings: Settings, request: Request
) -> AdminSessionModel:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _generic_http(401, request)
    try:
        claims = _service(db, settings).access.validate(authorization.split(" ", 1)[1])
    except ValueError as exc:
        raise _generic_http(401, request) from exc
    sess = db.get(AdminSessionModel, claims["session_id"])
    admin = db.get(AdminModel, claims["admin_id"])
    now = datetime.now(UTC)
    if (
        not sess
        or sess.revoked_at
        or sess.consumed_at
        or sess.idle_expires_at.replace(tzinfo=UTC) < now
        or sess.absolute_expires_at.replace(tzinfo=UTC) < now
        or not admin
        or admin.status != "ACTIVE"
    ):
        raise _generic_http(401, request)
    return sess


async def _check_rate(
    limiter: RateLimiter,
    request: Request,
    purpose: str,
    *parts: str,
    limit: int,
    window_seconds: int,
) -> None:
    try:
        result = await limiter.check(purpose, *parts, limit=limit, window_seconds=window_seconds)
    except RateLimitUnavailable as exc:
        raise _generic_http(503, request) from exc
    if not result.allowed:
        raise _generic_http(429, request, headers={"Retry-After": str(result.retry_after)})


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> LoginResponse:
    await _check_rate(
        limiter,
        request,
        "admin-login",
        body.email,
        request.client.host if request.client else "",
        limit=settings.admin_login_rate_limit,
        window_seconds=settings.admin_login_rate_limit_window_seconds,
    )
    result = _service(db, settings).login(
        body.email,
        body.password,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    if result["outcome"] == AuthenticationOutcome.INVALID_CREDENTIALS:
        raise _generic_http(401, request)
    if "refresh_token" in result:
        _set_cookie(response, settings, str(result["refresh_token"]))
    return LoginResponse(
        outcome=cast(AuthenticationOutcome, result["outcome"]),
        access_token=cast(str | None, result.get("access_token")),
        csrf_token=cast(str | None, result.get("csrf_token")),
        mfa_challenge=cast(str | None, result.get("mfa_challenge")),
    )


@router.post("/mfa/verify", response_model=LoginResponse)
async def mfa_verify(
    body: MfaVerifyRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
) -> LoginResponse:
    await _check_rate(limiter, request, "admin-mfa", body.challenge, limit=5, window_seconds=300)
    result = _service(db, settings).verify_mfa(body.challenge, body.code)
    if result["outcome"] != AuthenticationOutcome.AUTHENTICATED:
        raise _generic_http(401, request)
    _set_cookie(response, settings, str(result["refresh_token"]))
    return LoginResponse(
        outcome=AuthenticationOutcome.AUTHENTICATED,
        access_token=str(result["access_token"]),
        csrf_token=str(result["csrf_token"]),
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> LoginResponse:
    presented_refresh = body.refresh_token or request.cookies.get(
        settings.admin_refresh_cookie_name
    )
    if not presented_refresh:
        raise _generic_http(401, request)
    svc = _service(db, settings)
    sess = svc.session_for_refresh(presented_refresh)
    if sess is None or not svc.validate_csrf(sess, x_csrf_token):
        raise _generic_http(403, request)
    await _check_rate(limiter, request, "admin-refresh", sess.id, limit=30, window_seconds=300)
    try:
        result = svc.refresh(presented_refresh)
    except ValueError as exc:
        raise _generic_http(401, request) from exc
    _set_cookie(response, settings, result["refresh_token"])
    return LoginResponse(
        outcome=AuthenticationOutcome.AUTHENTICATED,
        access_token=result["access_token"],
        csrf_token=result["csrf_token"],
    )


@router.get("/csrf", response_model=LoginResponse)
def csrf_state(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> LoginResponse:
    sess = _current(authorization, db, settings, request)
    csrf_value = sess.csrf_token_hash or _service(db, settings).csrf_for(sess.id)
    sess.csrf_token_hash = csrf_value
    return LoginResponse(outcome=AuthenticationOutcome.AUTHENTICATED, csrf_token=csrf_value)


@router.get("/me", response_model=ProfileResponse)
def me(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> ProfileResponse:
    sess = _current(authorization, db, settings, request)
    return ProfileResponse.model_validate(
        _service(db, settings).current_profile(sess.admin_id, sess.id)
    )


@router.get("/sessions", response_model=list[SessionResponse])
def sessions(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> list[SessionResponse]:
    sess = _current(authorization, db, settings, request)
    return [
        SessionResponse.model_validate(row)
        for row in _service(db, settings).list_sessions(sess.admin_id, sess.id)
    ]


@router.post("/logout", response_model=OkResponse)
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    sess = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(sess, x_csrf_token):
        raise _generic_http(403, request)
    svc.revoke_session(sess.admin_id, sess.id)
    _clear_cookie(response, settings)
    return OkResponse()


@router.post("/sessions/{session_id}/revoke", response_model=OkResponse)
def revoke_one(
    session_id: str,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    current = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(current, x_csrf_token):
        raise _generic_http(403, request)
    try:
        svc.revoke_session(current.admin_id, session_id)
    except PermissionError as exc:
        raise _generic_http(404, request) from exc
    if session_id == current.id:
        _clear_cookie(response, settings)
    return OkResponse()


@router.post("/sessions/revoke-other", response_model=OkResponse)
def revoke_other(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    current = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(current, x_csrf_token):
        raise _generic_http(403, request)
    svc.revoke_sessions(current.admin_id, keep_session_id=current.id, reason="admin_revoked_others")
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
    current = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(current, x_csrf_token):
        raise _generic_http(403, request)
    svc.revoke_sessions(current.admin_id, keep_session_id=None, reason="admin_revoked_all")
    _clear_cookie(response, settings)
    return OkResponse()


@router.post("/password/change", response_model=OkResponse)
async def change_password(
    body: PasswordChangeRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    current = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(current, x_csrf_token):
        raise _generic_http(403, request)
    await _check_rate(limiter, request, "admin-password", current.id, limit=5, window_seconds=300)
    try:
        svc.change_password(current.admin_id, body.current_password, body.new_password, current.id)
    except ValueError as exc:
        raise _generic_http(400, request) from exc
    return OkResponse()


@router.post("/totp/begin", response_model=TotpBeginResponse)
def totp_begin(
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> TotpBeginResponse:
    sess = _current(authorization, db, settings, request)
    return TotpBeginResponse.model_validate(_service(db, settings).begin_totp(sess.admin_id))


@router.post("/totp/confirm", response_model=RecoveryCodesResponse)
def totp_confirm(
    body: TotpConfirmRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> RecoveryCodesResponse:
    sess = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(sess, x_csrf_token):
        raise _generic_http(403, request)
    try:
        codes = svc.confirm_totp(sess.admin_id, body.credential_id, body.code)
    except ValueError as exc:
        raise _generic_http(400, request) from exc
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/recovery-codes/regenerate", response_model=RecoveryCodesResponse)
async def regenerate_recovery_codes(
    body: StrongConfirmationRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> RecoveryCodesResponse:
    sess = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(sess, x_csrf_token):
        raise _generic_http(403, request)
    await _check_rate(
        limiter, request, "admin-recovery-regenerate", sess.id, limit=5, window_seconds=300
    )
    try:
        codes = svc.regenerate_recovery_codes(sess.admin_id, body.current_password, body.code)
    except ValueError as exc:
        raise _generic_http(400, request) from exc
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/totp/disable", response_model=OkResponse)
async def disable_totp(
    body: StrongConfirmationRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    authorization: Annotated[str | None, Header()] = None,
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> OkResponse:
    sess = _current(authorization, db, settings, request)
    svc = _service(db, settings)
    if not svc.validate_csrf(sess, x_csrf_token):
        raise _generic_http(403, request)
    await _check_rate(limiter, request, "admin-mfa-disable", sess.id, limit=5, window_seconds=300)
    try:
        svc.disable_totp(sess.admin_id, body.current_password, body.code, sess.id)
    except ValueError as exc:
        raise _generic_http(400, request) from exc
    return OkResponse()


# Public factory for sensitive application services that reuse admin reauthentication.
admin_auth_service = _service
