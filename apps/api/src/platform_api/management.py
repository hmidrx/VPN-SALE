from __future__ import annotations

from base64 import urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.identity import (
    AdminStatus,
    UserStatus,
    ensure_transition,
    normalize_email,
    sanitize_metadata,
)

from platform_api.admin_auth.service import AccessTokenService, PasswordPolicy
from platform_api.config import Settings, get_settings
from platform_api.database import get_db_session
from platform_api.identity.models import (
    AdminModel,
    AdminRoleAssignmentModel,
    AdminSessionModel,
    AuditLogModel,
    CustomerProfileModel,
    CustomerSessionModel,
    PermissionModel,
    RoleModel,
    RolePermissionModel,
    SecurityEventModel,
    TelegramAccountModel,
    TotpCredentialModel,
    UserModel,
)
from platform_api.identity.security import Argon2idPasswordHasher, OpaqueTokenService

router = APIRouter(prefix="/api/v1/admin/management", tags=["admin-management"])
public_router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])
MAX_REASON = 240
SUPER = "super_admin"


class ApiError(BaseModel):
    code: str
    message_key: str
    correlation_id: str


class Page(BaseModel):
    items: list[dict[str, Any]]
    next_cursor: str | None = None


class Reason(BaseModel):
    reason: str = Field(min_length=1, max_length=MAX_REASON)


class InviteRequest(BaseModel):
    email: str
    role_ids: list[str] = Field(default_factory=list, max_length=20)
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class InviteResponse(BaseModel):
    administrator: dict[str, Any]
    invitation_token: str


class AcceptInvitationRequest(BaseModel):
    invitation_token: str = Field(min_length=32, max_length=512)
    password: str = Field(min_length=1, max_length=1024)


class UpdateAdminRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=MAX_REASON)


class RoleCreateRequest(BaseModel):
    machine_name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    display_name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=240)


class RoleUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=240)
    active: bool | None = None
    reason: str = Field(min_length=1, max_length=MAX_REASON)


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    locale: str | None = Field(default=None, max_length=16)
    reason: str = Field(min_length=1, max_length=MAX_REASON)


class SecurityNote(BaseModel):
    note: str | None = Field(default=None, max_length=500)


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _err(status: int, request: Request, code: str) -> HTTPException:
    return HTTPException(
        status,
        detail=ApiError(
            code=code, message_key=f"management.{code}", correlation_id=_cid(request)
        ).model_dump(),
    )


def _cursor(dt: datetime, ident: str) -> str:
    return urlsafe_b64encode(f"{dt.isoformat()}|{ident}".encode()).decode()


def _limit(v: int | None) -> int:
    return min(max(v or 50, 1), 100)


def _audit(
    db: Session,
    actor: str,
    code: str,
    target_type: str,
    target_id: str | None,
    request: Request,
    metadata: dict[str, object] | None = None,
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=actor,
            target_type=target_type,
            target_id=target_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            metadata_=sanitize_metadata(metadata or {}),
        )
    )


def _active_permissions(db: Session, admin_id: str) -> set[str]:
    rows = db.execute(
        select(PermissionModel.code)
        .join(RolePermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
        .join(RoleModel, RoleModel.id == RolePermissionModel.role_id)
        .join(AdminRoleAssignmentModel, AdminRoleAssignmentModel.role_id == RoleModel.id)
        .where(AdminRoleAssignmentModel.admin_id == admin_id, RoleModel.active.is_(True))
    ).all()
    return {r[0] for r in rows}


def current_admin(
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AdminModel:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _err(401, request, "unauthenticated")
    try:
        claims = AccessTokenService(settings).validate(authorization.split(" ", 1)[1])
    except ValueError as exc:
        raise _err(401, request, "unauthenticated") from exc
    sess = db.get(AdminSessionModel, claims["session_id"])
    admin = db.get(AdminModel, claims["admin_id"])
    now = datetime.now(UTC)
    if (
        not sess
        or not admin
        or sess.revoked_at
        or sess.consumed_at
        or admin.status != AdminStatus.ACTIVE.value
        or sess.idle_expires_at.replace(tzinfo=UTC) < now
        or sess.absolute_expires_at.replace(tzinfo=UTC) < now
    ):
        raise _err(401, request, "unauthenticated")
    return admin


def require_perm(code: str):
    def dep(
        admin: Annotated[AdminModel, Depends(current_admin)],
        db: Annotated[Session, Depends(get_db_session)],
        request: Request,
    ) -> AdminModel:
        if code not in _active_permissions(db, admin.id):
            db.add(
                SecurityEventModel(
                    actor_type="admin",
                    actor_id=admin.id,
                    event_code="authorization.denied",
                    occurred_at=datetime.now(UTC),
                    correlation_id=_cid(request),
                    severity="WARNING",
                    status="OPEN",
                    metadata_={"permission": code},
                )
            )
            raise _err(403, request, "forbidden")
        return admin

    return dep


def _admin_view(db: Session, a: AdminModel) -> dict[str, Any]:
    roles = db.execute(
        select(RoleModel.id, RoleModel.machine_name, RoleModel.display_name)
        .join(AdminRoleAssignmentModel, AdminRoleAssignmentModel.role_id == RoleModel.id)
        .where(AdminRoleAssignmentModel.admin_id == a.id)
    ).all()
    sessions = db.scalar(
        select(func.count())
        .select_from(AdminSessionModel)
        .where(AdminSessionModel.admin_id == a.id, AdminSessionModel.revoked_at.is_(None))
    )
    mfa = db.scalar(
        select(func.count())
        .select_from(TotpCredentialModel)
        .where(
            TotpCredentialModel.admin_id == a.id,
            TotpCredentialModel.revoked_at.is_(None),
            TotpCredentialModel.confirmed_at.is_not(None),
        )
    )
    return {
        "id": a.id,
        "email": a.normalized_email,
        "status": a.status,
        "roles": [{"id": r[0], "machine_name": r[1], "display_name": r[2]} for r in roles],
        "mfa_enabled": bool(mfa),
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
        "password_changed_at": a.password_changed_at.isoformat() if a.password_changed_at else None,
        "last_successful_login_at": a.last_successful_login_at.isoformat()
        if a.last_successful_login_at
        else None,
        "last_failed_login_at": a.last_failed_login_at.isoformat()
        if a.last_failed_login_at
        else None,
        "failed_login_count": a.failed_login_count,
        "lock_until": a.lock_until.isoformat() if a.lock_until else None,
        "active_session_count": sessions or 0,
    }


@router.get("/admins", response_model=Page)
def list_admins(
    db: Annotated[Session, Depends(get_db_session)],
    admin: Annotated[AdminModel, Depends(require_perm("admins.read"))],
    limit: int | None = None,
) -> Page:
    rows = db.scalars(
        select(AdminModel)
        .order_by(AdminModel.created_at.desc(), AdminModel.id.desc())
        .limit(_limit(limit) + 1)
    ).all()
    items = [_admin_view(db, x) for x in rows[: _limit(limit)]]
    return Page(
        items=items,
        next_cursor=_cursor(rows[_limit(limit) - 1].created_at, rows[_limit(limit) - 1].id)
        if len(rows) > _limit(limit)
        else None,
    )


@router.get("/admins/{admin_id}")
def get_admin(
    admin_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.read"))],
) -> dict[str, Any]:
    a = db.get(AdminModel, admin_id)
    if not a:
        raise HTTPException(404)
    return _admin_view(db, a)


@router.post("/admins/invitations", response_model=InviteResponse)
def invite(
    body: InviteRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.invite"))],
) -> InviteResponse:
    token_service = OpaqueTokenService()
    raw = token_service.generate()
    now = datetime.now(UTC)
    roles: list[RoleModel] = list(
        db.scalars(
            select(RoleModel).where(RoleModel.id.in_(body.role_ids), RoleModel.active.is_(True))
        ).all()
        if body.role_ids
        else []
    )
    a = AdminModel(
        normalized_email=normalize_email(body.email),
        password_hash="invited-password-not-set",  # noqa: S106
        status="INVITED",
        invitation_token_hash=token_service.hash(raw),
        invitation_expires_at=now + timedelta(hours=body.expires_in_hours),
        created_at=now,
        updated_at=now,
    )
    db.add(a)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _err(409, request, "duplicate_email") from exc
    for r in roles:
        db.add(AdminRoleAssignmentModel(admin_id=a.id, role_id=r.id))
    _audit(
        db,
        actor.id,
        "admin.invited",
        "admin",
        a.id,
        request,
        {"roles": [r.machine_name for r in roles]},
    )
    return InviteResponse(administrator=_admin_view(db, a), invitation_token=raw)


@public_router.post("/accept-invitation")
def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    token_service = OpaqueTokenService()
    now = datetime.now(UTC)
    h = token_service.hash(body.invitation_token)
    a = db.scalar(select(AdminModel).where(AdminModel.invitation_token_hash == h))
    if (
        not a
        or a.status != "INVITED"
        or a.invitation_revoked_at
        or not a.invitation_expires_at
        or a.invitation_expires_at.replace(tzinfo=UTC) < now
    ):
        raise _err(401, request, "invalid_invitation")
    PasswordPolicy(settings.admin_password_min_length, settings.admin_password_max_length).validate(
        body.password, email=a.normalized_email
    )
    a.password_hash = Argon2idPasswordHasher(
        settings.password_argon2_time_cost,
        settings.password_argon2_memory_cost,
        settings.password_argon2_parallelism,
    ).hash(body.password)
    a.status = "ACTIVE"
    a.invitation_accepted_at = now
    a.invitation_token_hash = None
    a.password_changed_at = now
    a.updated_at = now
    _audit(db, a.id, "admin.activated", "admin", a.id, request)
    return {"ok": True}


# dynamic admin status and sessions
@router.post("/admins/{admin_id}/disable")
def disable_admin(
    admin_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.disable"))],
) -> dict[str, bool]:
    a = db.get(AdminModel, admin_id)
    if not a:
        raise HTTPException(404)
    if a.id == actor.id:
        raise _err(409, request, "unsafe_self_change")
    _ensure_not_final_super(db, a.id, request)
    ensure_transition(AdminStatus(a.status), AdminStatus.DISABLED)
    a.status = "DISABLED"
    a.updated_at = datetime.now(UTC)
    db.execute(
        update(AdminSessionModel)
        .where(AdminSessionModel.admin_id == a.id, AdminSessionModel.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revocation_reason="admin_disabled")
    )
    _audit(db, actor.id, "admin.disabled", "admin", a.id, request, {"reason": body.reason})
    return {"ok": True}


@router.post("/admins/{admin_id}/lock")
def lock_admin(
    admin_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.update"))],
) -> dict[str, bool]:
    a = db.get(AdminModel, admin_id)
    if not a:
        raise HTTPException(404)
    ensure_transition(AdminStatus(a.status), AdminStatus.LOCKED)
    a.status = "LOCKED"
    a.updated_at = datetime.now(UTC)
    _audit(db, actor.id, "admin.locked", "admin", a.id, request, {"reason": body.reason})
    return {"ok": True}


@router.post("/admins/{admin_id}/unlock")
def unlock_admin(
    admin_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.unlock"))],
) -> dict[str, bool]:
    a = db.get(AdminModel, admin_id)
    if not a:
        raise HTTPException(404)
    ensure_transition(AdminStatus(a.status), AdminStatus.ACTIVE)
    a.status = "ACTIVE"
    a.lock_until = None
    a.updated_at = datetime.now(UTC)
    _audit(db, actor.id, "admin.unlocked", "admin", a.id, request, {"reason": body.reason})
    return {"ok": True}


def _ensure_not_final_super(db: Session, target_admin_id: str, request: Request) -> None:
    role = db.scalar(select(RoleModel).where(RoleModel.machine_name == SUPER))
    if not role:
        return
    has = db.get(AdminRoleAssignmentModel, {"admin_id": target_admin_id, "role_id": role.id})
    if not has:
        return
    count = (
        db.scalar(
            select(func.count())
            .select_from(AdminModel)
            .join(AdminRoleAssignmentModel, AdminModel.id == AdminRoleAssignmentModel.admin_id)
            .where(AdminRoleAssignmentModel.role_id == role.id, AdminModel.status == "ACTIVE")
        )
        or 0
    )
    if count <= 1:
        raise _err(409, request, "final_super_admin")


@router.get("/admins/{admin_id}/roles")
def admin_roles(
    admin_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.read"))],
) -> list[dict[str, Any]]:
    return [
        {"id": r.id, "machine_name": r.machine_name, "display_name": r.display_name}
        for r in db.scalars(
            select(RoleModel)
            .join(AdminRoleAssignmentModel, RoleModel.id == AdminRoleAssignmentModel.role_id)
            .where(AdminRoleAssignmentModel.admin_id == admin_id)
        ).all()
    ]


@router.post("/admins/{admin_id}/roles/{role_id}")
def assign_role(
    admin_id: str,
    role_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.roles.manage"))],
) -> dict[str, bool]:
    db.add(AdminRoleAssignmentModel(admin_id=admin_id, role_id=role_id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"ok": True}
    _audit(db, actor.id, "admin.role.assigned", "admin", admin_id, request, {"role_id": role_id})
    return {"ok": True}


@router.delete("/admins/{admin_id}/roles/{role_id}")
def remove_role(
    admin_id: str,
    role_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("admins.roles.manage"))],
) -> dict[str, bool]:
    role = db.get(RoleModel, role_id)
    if role and role.machine_name == SUPER:
        _ensure_not_final_super(db, admin_id, request)
    row = db.get(AdminRoleAssignmentModel, {"admin_id": admin_id, "role_id": role_id})
    if row:
        db.delete(row)
        _audit(db, actor.id, "admin.role.removed", "admin", admin_id, request, {"role_id": role_id})
    return {"ok": True}


@router.get("/admins/{admin_id}/sessions")
def admin_sessions(
    admin_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("sessions.read"))],
) -> list[dict[str, Any]]:
    return [
        {
            "session_id": s.id,
            "created_at": s.created_at.isoformat(),
            "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
            "revoked": bool(s.revoked_at),
            "device_label": s.device_label,
        }
        for s in db.scalars(
            select(AdminSessionModel)
            .where(AdminSessionModel.admin_id == admin_id)
            .order_by(AdminSessionModel.created_at.desc())
        ).all()
    ]


@router.delete("/admins/{admin_id}/sessions/{session_id}")
def revoke_admin_session(
    admin_id: str,
    session_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("sessions.revoke"))],
) -> dict[str, bool]:
    s = db.get(AdminSessionModel, session_id)
    now = datetime.now(UTC)
    if s and s.admin_id == admin_id and not s.revoked_at:
        s.revoked_at = now
        s.revocation_reason = "operator_revoked"
        _audit(db, actor.id, "admin.session.revoked", "admin_session", session_id, request)
    return {"ok": True}


@router.delete("/admins/{admin_id}/sessions")
def revoke_all_admin_sessions(
    admin_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("sessions.revoke"))],
) -> dict[str, bool]:
    db.execute(
        update(AdminSessionModel)
        .where(AdminSessionModel.admin_id == admin_id, AdminSessionModel.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revocation_reason="operator_revoked_all")
    )
    _audit(db, actor.id, "admin.sessions.revoked", "admin", admin_id, request)
    return {"ok": True}


@router.get("/roles", response_model=Page)
def list_roles(
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.read"))],
) -> Page:
    return Page(
        items=[
            {
                "id": r.id,
                "machine_name": r.machine_name,
                "display_name": r.display_name,
                "description": r.description,
                "built_in": r.built_in,
                "active": r.active,
            }
            for r in db.scalars(select(RoleModel).order_by(RoleModel.machine_name)).all()
        ]
    )


@router.post("/roles")
def create_role(
    body: RoleCreateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.create"))],
) -> dict[str, Any]:
    r = RoleModel(
        machine_name=body.machine_name,
        display_name=body.display_name,
        description=body.description,
        built_in=False,
        active=True,
    )
    db.add(r)
    try:
        db.flush()
    except IntegrityError as exc:
        raise _err(409, request, "duplicate_role") from exc
    _audit(db, actor.id, "role.created", "role", r.id, request)
    return {
        "id": r.id,
        "machine_name": r.machine_name,
        "display_name": r.display_name,
        "built_in": False,
        "active": True,
    }


@router.get("/roles/{role_id}")
def get_role(
    role_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.read"))],
) -> dict[str, Any]:
    r = db.get(RoleModel, role_id)
    if not r:
        raise HTTPException(404)
    return {
        "id": r.id,
        "machine_name": r.machine_name,
        "display_name": r.display_name,
        "description": r.description,
        "built_in": r.built_in,
        "active": r.active,
    }


@router.patch("/roles/{role_id}")
def update_role(
    role_id: str,
    body: RoleUpdateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.update"))],
) -> dict[str, bool]:
    r = db.get(RoleModel, role_id)
    if not r:
        raise HTTPException(404)
    if r.built_in and body.active is False:
        raise _err(409, request, "protected_role")
    if body.display_name is not None:
        r.display_name = body.display_name
    if body.description is not None:
        r.description = body.description
    if body.active is not None:
        r.active = body.active
    r.updated_at = datetime.now(UTC)
    _audit(db, actor.id, "role.updated", "role", r.id, request, {"reason": body.reason})
    return {"ok": True}


@router.get("/roles/{role_id}/permissions")
def role_perms(
    role_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.read"))],
) -> list[dict[str, str]]:
    return [
        {"id": p.id, "code": p.code, "description": p.description}
        for p in db.scalars(
            select(PermissionModel)
            .join(RolePermissionModel, PermissionModel.id == RolePermissionModel.permission_id)
            .where(RolePermissionModel.role_id == role_id)
        ).all()
    ]


@router.post("/roles/{role_id}/permissions/{permission_id}")
def add_perm(
    role_id: str,
    permission_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.permissions.manage"))],
) -> dict[str, bool]:
    db.add(RolePermissionModel(role_id=role_id, permission_id=permission_id))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"ok": True}
    _audit(
        db,
        actor.id,
        "role.permission.assigned",
        "role",
        role_id,
        request,
        {"permission_id": permission_id},
    )
    return {"ok": True}


@router.delete("/roles/{role_id}/permissions/{permission_id}")
def del_perm(
    role_id: str,
    permission_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.permissions.manage"))],
) -> dict[str, bool]:
    row = db.get(RolePermissionModel, {"role_id": role_id, "permission_id": permission_id})
    if row:
        db.delete(row)
        _audit(
            db,
            actor.id,
            "role.permission.removed",
            "role",
            role_id,
            request,
            {"permission_id": permission_id},
        )
    return {"ok": True}


@router.get("/roles/{role_id}/admins")
def role_admins(
    role_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.read"))],
) -> list[dict[str, Any]]:
    return [
        _admin_view(db, a)
        for a in db.scalars(
            select(AdminModel)
            .join(AdminRoleAssignmentModel, AdminModel.id == AdminRoleAssignmentModel.admin_id)
            .where(AdminRoleAssignmentModel.role_id == role_id)
        ).all()
    ]


@router.get("/permissions", response_model=Page)
def permissions(
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.read"))],
    group: Literal["namespace"] | None = None,
) -> Page:
    rows = db.scalars(select(PermissionModel).order_by(PermissionModel.code)).all()
    items = [
        {
            "id": p.id,
            "code": p.code,
            "description": p.description,
            "namespace": p.code.split(".", 1)[0],
        }
        for p in rows
    ]
    return Page(items=items)


@router.get("/permissions/{permission_id}")
def permission_detail(
    permission_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("roles.read"))],
) -> dict[str, str]:
    p = db.get(PermissionModel, permission_id)
    if not p:
        raise HTTPException(404)
    return {"id": p.id, "code": p.code, "description": p.description}


@router.get("/users", response_model=Page)
def list_users(
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.read"))],
    status: str | None = None,
    telegram_user_id: int | None = None,
    username: str | None = None,
) -> Page:
    stmt = (
        select(UserModel, CustomerProfileModel, TelegramAccountModel)
        .join(CustomerProfileModel, CustomerProfileModel.user_id == UserModel.id, isouter=True)
        .join(TelegramAccountModel, TelegramAccountModel.user_id == UserModel.id, isouter=True)
        .order_by(UserModel.created_at.desc(), UserModel.id.desc())
        .limit(101)
    )
    if status:
        stmt = stmt.where(UserModel.status == status)
    if telegram_user_id:
        stmt = stmt.where(TelegramAccountModel.telegram_user_id == telegram_user_id)
    if username:
        stmt = stmt.where(
            TelegramAccountModel.username.like(username[:32].casefold().replace("%", "") + "%")
        )
    return Page(items=[_user_view(db, u, p, t) for u, p, t in db.execute(stmt).all()])


def _user_view(
    db: Session, u: UserModel, p: CustomerProfileModel | None, t: TelegramAccountModel | None
) -> dict[str, Any]:
    cnt = (
        db.scalar(
            select(func.count())
            .select_from(CustomerSessionModel)
            .where(CustomerSessionModel.user_id == u.id, CustomerSessionModel.revoked_at.is_(None))
        )
        or 0
    )
    return {
        "id": u.id,
        "status": u.status,
        "created_at": u.created_at.isoformat(),
        "updated_at": u.updated_at.isoformat(),
        "profile": {
            "display_name": p.display_name if p else None,
            "locale": p.locale if p else None,
        },
        "telegram": {
            "telegram_user_id": t.telegram_user_id if t else None,
            "username": t.username if t else None,
            "first_name": t.first_name if t else None,
            "last_name": t.last_name if t else None,
            "language_code": t.language_code if t else None,
            "first_seen_at": t.first_seen_at.isoformat() if t else None,
            "last_seen_at": t.last_seen_at.isoformat() if t else None,
            "bot_started": t.bot_started if t else None,
            "blocked_bot": t.blocked_bot if t else None,
        },
        "active_session_count": cnt,
    }


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.read"))],
) -> dict[str, Any]:
    u = db.get(UserModel, user_id)
    if not u:
        raise HTTPException(404)
    p = db.get(CustomerProfileModel, user_id)
    t = db.scalar(select(TelegramAccountModel).where(TelegramAccountModel.user_id == user_id))
    return _user_view(db, u, p, t)


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.update"))],
) -> dict[str, bool]:
    p = db.get(CustomerProfileModel, user_id) or CustomerProfileModel(user_id=user_id)
    db.add(p)
    p.display_name = body.display_name
    p.locale = body.locale
    _audit(
        db,
        actor.id,
        "customer.profile.updated",
        "customer",
        user_id,
        request,
        {"reason": body.reason},
    )
    return {"ok": True}


def _set_user_status(
    user_id: str, target: str, body: Reason, request: Request, db: Session, actor: AdminModel
) -> dict[str, bool]:
    u = db.get(UserModel, user_id)
    if not u:
        raise HTTPException(404)
    ensure_transition(UserStatus(u.status), UserStatus(target))
    u.status = target
    u.updated_at = datetime.now(UTC)
    if target in {"SUSPENDED", "BLOCKED", "DEACTIVATED"}:
        db.execute(
            update(CustomerSessionModel)
            .where(
                CustomerSessionModel.user_id == user_id, CustomerSessionModel.revoked_at.is_(None)
            )
            .values(revoked_at=datetime.now(UTC), revocation_reason=f"customer_{target.casefold()}")
        )
    _audit(
        db,
        actor.id,
        f"customer.{target.casefold()}",
        "customer",
        user_id,
        request,
        {"reason": body.reason},
    )
    return {"ok": True}


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.activate"))],
) -> dict[str, bool]:
    return _set_user_status(user_id, "ACTIVE", body, request, db, actor)


@router.post("/users/{user_id}/suspend")
def suspend_user(
    user_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.suspend"))],
) -> dict[str, bool]:
    return _set_user_status(user_id, "SUSPENDED", body, request, db, actor)


@router.post("/users/{user_id}/block")
def block_user(
    user_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.block"))],
) -> dict[str, bool]:
    return _set_user_status(user_id, "BLOCKED", body, request, db, actor)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: str,
    body: Reason,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.deactivate"))],
) -> dict[str, bool]:
    return _set_user_status(user_id, "DEACTIVATED", body, request, db, actor)


@router.get("/users/{user_id}/telegram")
def user_telegram(
    user_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("users.read"))],
) -> dict[str, Any]:
    t = db.scalar(select(TelegramAccountModel).where(TelegramAccountModel.user_id == user_id))
    return (
        {}
        if not t
        else {
            "telegram_user_id": t.telegram_user_id,
            "username": t.username,
            "first_name": t.first_name,
            "last_name": t.last_name,
            "language_code": t.language_code,
            "bot_started": t.bot_started,
            "blocked_bot": t.blocked_bot,
        }
    )


@router.get("/users/{user_id}/sessions")
def user_sessions(
    user_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("sessions.read"))],
) -> list[dict[str, Any]]:
    return [
        {
            "session_id": s.id,
            "created_at": s.created_at.isoformat(),
            "last_used_at": s.last_used_at.isoformat() if s.last_used_at else None,
            "revoked": bool(s.revoked_at),
            "device_label": s.device_label,
        }
        for s in db.scalars(
            select(CustomerSessionModel)
            .where(CustomerSessionModel.user_id == user_id)
            .order_by(CustomerSessionModel.created_at.desc())
        ).all()
    ]


@router.delete("/users/{user_id}/sessions/{session_id}")
def revoke_user_session(
    user_id: str,
    session_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("sessions.revoke"))],
) -> dict[str, bool]:
    s = db.get(CustomerSessionModel, session_id)
    if s and s.user_id == user_id and not s.revoked_at:
        s.revoked_at = datetime.now(UTC)
        s.revocation_reason = "operator_revoked"
        _audit(db, actor.id, "customer.session.revoked", "customer_session", session_id, request)
    return {"ok": True}


@router.delete("/users/{user_id}/sessions")
def revoke_user_sessions(
    user_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("sessions.revoke"))],
) -> dict[str, bool]:
    db.execute(
        update(CustomerSessionModel)
        .where(CustomerSessionModel.user_id == user_id, CustomerSessionModel.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC), revocation_reason="operator_revoked_all")
    )
    _audit(db, actor.id, "customer.sessions.revoked", "customer", user_id, request)
    return {"ok": True}


@router.get("/audit-logs", response_model=Page)
def audit_logs(
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("audit.read"))],
    event_code: str | None = None,
    actor_type: str | None = None,
    target_type: str | None = None,
) -> Page:
    stmt = (
        select(AuditLogModel)
        .order_by(AuditLogModel.occurred_at.desc(), AuditLogModel.id.desc())
        .limit(101)
    )
    if event_code:
        stmt = stmt.where(AuditLogModel.event_code == event_code[:120])
    if actor_type:
        stmt = stmt.where(AuditLogModel.actor_type == actor_type[:32])
    if target_type:
        stmt = stmt.where(AuditLogModel.target_type == target_type[:80])
    return Page(
        items=[
            {
                "id": x.id,
                "actor_type": x.actor_type,
                "actor_id": x.actor_id,
                "target_type": x.target_type,
                "target_id": x.target_id,
                "event_code": x.event_code,
                "occurred_at": x.occurred_at.isoformat(),
                "correlation_id": x.correlation_id,
                "metadata": x.metadata_,
            }
            for x in db.scalars(stmt).all()
        ]
    )


@router.get("/audit-logs/{event_id}")
def audit_detail(
    event_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("audit.read"))],
) -> dict[str, Any]:
    x = db.get(AuditLogModel, event_id)
    if not x:
        raise HTTPException(404)
    return {
        "id": x.id,
        "actor_type": x.actor_type,
        "actor_id": x.actor_id,
        "target_type": x.target_type,
        "target_id": x.target_id,
        "event_code": x.event_code,
        "occurred_at": x.occurred_at.isoformat(),
        "correlation_id": x.correlation_id,
        "metadata": x.metadata_,
    }


@router.get("/security-events", response_model=Page)
def security_events(
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("security.read"))],
    status: str | None = None,
    severity: str | None = None,
) -> Page:
    stmt = (
        select(SecurityEventModel)
        .order_by(SecurityEventModel.occurred_at.desc(), SecurityEventModel.id.desc())
        .limit(101)
    )
    if status:
        stmt = stmt.where(SecurityEventModel.status == status[:16])
    if severity:
        stmt = stmt.where(SecurityEventModel.severity == severity[:16])
    return Page(items=[_sec_view(x) for x in db.scalars(stmt).all()])


def _sec_view(x: SecurityEventModel) -> dict[str, Any]:
    return {
        "id": x.id,
        "actor_type": x.actor_type,
        "actor_id": x.actor_id,
        "event_code": x.event_code,
        "occurred_at": x.occurred_at.isoformat(),
        "correlation_id": x.correlation_id,
        "severity": x.severity,
        "status": x.status,
        "acknowledged_at": x.acknowledged_at.isoformat() if x.acknowledged_at else None,
        "resolved_at": x.resolved_at.isoformat() if x.resolved_at else None,
        "resolution_note": x.resolution_note,
        "metadata": x.metadata_,
    }


@router.get("/security-events/{event_id}")
def security_detail(
    event_id: str,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("security.read"))],
) -> dict[str, Any]:
    x = db.get(SecurityEventModel, event_id)
    if not x:
        raise HTTPException(404)
    return _sec_view(x)


@router.post("/security-events/{event_id}/acknowledge")
def ack_security(
    event_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("security.acknowledge"))],
) -> dict[str, bool]:
    x = db.get(SecurityEventModel, event_id)
    if not x:
        raise HTTPException(404)
    if not x.acknowledged_at:
        x.acknowledged_at = datetime.now(UTC)
        x.acknowledged_by_admin_id = actor.id
        x.status = "ACKNOWLEDGED"
        _audit(db, actor.id, "security_event.acknowledged", "security_event", event_id, request)
    return {"ok": True}


@router.post("/security-events/{event_id}/resolve")
def resolve_security(
    event_id: str,
    body: SecurityNote,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("security.manage"))],
) -> dict[str, bool]:
    x = db.get(SecurityEventModel, event_id)
    if not x:
        raise HTTPException(404)
    x.resolved_at = datetime.now(UTC)
    x.resolved_by_admin_id = actor.id
    x.resolution_note = body.note
    x.status = "RESOLVED"
    _audit(db, actor.id, "security_event.resolved", "security_event", event_id, request)
    return {"ok": True}


@router.post("/security-events/{event_id}/reopen")
def reopen_security(
    event_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db_session)],
    actor: Annotated[AdminModel, Depends(require_perm("security.manage"))],
) -> dict[str, bool]:
    x = db.get(SecurityEventModel, event_id)
    if not x:
        raise HTTPException(404)
    x.status = "OPEN"
    x.resolved_at = None
    x.resolved_by_admin_id = None
    _audit(db, actor.id, "security_event.reopened", "security_event", event_id, request)
    return {"ok": True}
