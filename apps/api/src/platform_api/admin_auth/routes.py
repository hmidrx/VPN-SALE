from __future__ import annotations

from collections.abc import Generator
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from platform_api.config import Settings, get_settings
from platform_api.identity.models import AdminModel, AdminSessionModel
from platform_api.identity.security import (
    Argon2idPasswordHasher,
    deterministic_development_fernet_key,
)

from .service import (
    GENERIC_AUTH_ERROR,
    AdminAuthService,
    AuthenticationOutcome,
    FixedWindowRateLimiter,
)

router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])
_limiter = FixedWindowRateLimiter(limit=10, window_seconds=300)


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=1024)


class MfaVerifyRequest(BaseModel):
    challenge: str
    code: str


class TotpConfirmRequest(BaseModel):
    credential_id: str
    code: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://").replace(
        "sqlite+aiosqlite://", "sqlite://"
    )


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Generator[Session, None, None]:
    engine = create_engine(_sync_url(settings.database_url))
    with Session(engine) as session:
        yield session


def _service(db: Session, settings: Settings) -> AdminAuthService:
    if not settings.identity_encryption_key:
        settings.identity_encryption_key = deterministic_development_fernet_key()
    hasher = Argon2idPasswordHasher(
        settings.password_argon2_time_cost,
        settings.password_argon2_memory_cost,
        settings.password_argon2_parallelism,
    )
    return AdminAuthService(db, settings, hasher, _limiter)


def _set_cookie(response: Response, settings: Settings, refresh: str) -> None:
    response.set_cookie(
        settings.admin_refresh_cookie_name,
        refresh,
        httponly=True,
        secure=settings.admin_refresh_cookie_secure,
        samesite=cast(Literal["lax", "strict", "none"], settings.admin_refresh_cookie_samesite),
        path=settings.admin_refresh_cookie_path,
        domain=settings.admin_refresh_cookie_domain or None,
    )


def _clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.admin_refresh_cookie_name,
        path=settings.admin_refresh_cookie_path,
        domain=settings.admin_refresh_cookie_domain or None,
    )


def _current(authorization: str | None, db: Session, settings: Settings) -> AdminSessionModel:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, detail=GENERIC_AUTH_ERROR)
    claims = AdminAuthService(db, settings, Argon2idPasswordHasher()).access.validate(
        authorization.split(" ", 1)[1]
    )
    sess = db.get(AdminSessionModel, claims["session_id"])
    admin = db.get(AdminModel, claims["admin_id"])
    if not sess or sess.revoked_at or not admin or admin.status != "ACTIVE":
        raise HTTPException(401, detail=GENERIC_AUTH_ERROR)
    return sess


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    result = _service(db, settings).login(
        body.email,
        body.password,
        ip=request.client.host if request.client else "",
        user_agent=request.headers.get("user-agent", ""),
    )
    db.commit()
    if result["outcome"] == AuthenticationOutcome.RATE_LIMITED:
        raise HTTPException(
            429,
            detail=GENERIC_AUTH_ERROR,
            headers={"Retry-After": str(result.get("retry_after", 60))},
        )
    if result["outcome"] == AuthenticationOutcome.INVALID_CREDENTIALS:
        raise HTTPException(401, detail=GENERIC_AUTH_ERROR)
    if "refresh_token" in result:
        _set_cookie(response, settings, str(result["refresh_token"]))
        result = {k: v for k, v in result.items() if k != "refresh_token"}
    return result


@router.post("/mfa/verify")
def mfa_verify(
    body: MfaVerifyRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    result = _service(db, settings).verify_mfa(body.challenge, body.code)
    db.commit()
    if result["outcome"] != AuthenticationOutcome.AUTHENTICATED:
        raise HTTPException(401, detail=GENERIC_AUTH_ERROR)
    _set_cookie(response, settings, str(result["refresh_token"]))
    return {k: v for k, v in result.items() if k != "refresh_token"}


@router.post("/refresh")
def refresh(
    body: RefreshRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    token = body.refresh_token or request.cookies.get(settings.admin_refresh_cookie_name)
    if not token:
        raise HTTPException(401, detail=GENERIC_AUTH_ERROR)
    try:
        result = _service(db, settings).refresh(token)
        db.commit()
    except ValueError as exc:
        db.commit()
        raise HTTPException(401, detail=GENERIC_AUTH_ERROR) from exc
    _set_cookie(response, settings, result["refresh_token"])
    return {k: v for k, v in result.items() if k != "refresh_token"}


@router.get("/me")
def me(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    sess = _current(authorization, db, settings)
    return {"admin_id": sess.admin_id, "session_id": sess.id}


@router.post("/logout")
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    sess = _current(authorization, db, settings)
    sess.revoked_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
    sess.revocation_reason = "logout"
    db.commit()
    _clear_cookie(response, settings)
    return {"ok": True}


@router.get("/sessions")
def sessions(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> list[dict[str, object]]:
    sess = _current(authorization, db, settings)
    return [
        {
            "session_id": s.id,
            "current": s.id == sess.id,
            "created_at": s.created_at.isoformat(),
            "revoked": s.revoked_at is not None,
        }
        for s in db.query(AdminSessionModel)
        .filter(AdminSessionModel.admin_id == sess.admin_id)
        .all()
    ]


@router.post("/totp/begin")
def totp_begin(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    sess = _current(authorization, db, settings)
    result = _service(db, settings).begin_totp(sess.admin_id)
    db.commit()
    return result


@router.post("/totp/confirm")
def totp_confirm(
    body: TotpConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, list[str]]:
    sess = _current(authorization, db, settings)
    codes = _service(db, settings).confirm_totp(sess.admin_id, body.credential_id, body.code)
    db.commit()
    return {"recovery_codes": codes}
