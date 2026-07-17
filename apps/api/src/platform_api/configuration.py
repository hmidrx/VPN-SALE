from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from vpnsale_domain.configuration import Draft, compiled_defaults, publish, validate_snapshot
from vpnsale_domain.identity import sanitize_metadata

from .configuration_models import (
    ConfigurationDraftModel,
    ConfigurationReleaseModel,
    ConfigurationValidationRunModel,
    RuntimeConfigurationSnapshotModel,
)
from .database import get_db_session
from .identity.models import AuditLogModel, SecurityEventModel
from .management import _active_permissions, current_admin  # pyright: ignore[reportPrivateUsage]

public_router = APIRouter(prefix="/api/v1/runtime/configuration", tags=["runtime-configuration"])
admin_router = APIRouter(prefix="/api/v1/admin/configuration", tags=["admin-configuration"])


class DraftCreate(BaseModel):
    clone_active: bool = True


class SectionUpdate(BaseModel):
    section: str = Field(min_length=1, max_length=64)
    value: dict[str, Any] | list[Any] | str | bool
    expected_version: int = Field(ge=1)


class PreviewCreate(BaseModel):
    channel: str = Field(pattern="^(customer-web|telegram-mini-app|telegram-bot)$")


class RuntimeContext(BaseModel):
    channel: str = "customer-web"
    locale: str = "fa"
    authenticated: bool = False
    role_category: str = "anonymous"
    subject_key: str = "anonymous"


def _cid(request: Request) -> str:
    return request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or "local"


def _err(status: int, code: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message_key": f"configuration.{code}"})


def _permitted(db: Session, admin_id: str, perm: str) -> bool:
    return perm in _active_permissions(db, admin_id)


def _audit(
    db: Session, admin_id: str, code: str, request: Request, meta: dict[str, object] | None = None
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin_id,
            target_type="configuration",
            target_id=None,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            metadata_=sanitize_metadata(meta or {}),
        )
    )


def _security(
    db: Session,
    admin_id: str | None,
    code: str,
    request: Request,
    meta: dict[str, object] | None = None,
) -> None:
    db.add(
        SecurityEventModel(
            actor_type="admin" if admin_id else "system",
            actor_id=admin_id,
            event_code=code,
            occurred_at=datetime.now(UTC),
            correlation_id=_cid(request),
            severity="WARNING",
            status="OPEN",
            metadata_=sanitize_metadata(meta or {}),
        )
    )


def _active_snapshot(db: Session) -> tuple[dict[str, Any], str, int]:
    snap = db.scalar(
        select(RuntimeConfigurationSnapshotModel)
        .order_by(RuntimeConfigurationSnapshotModel.created_at.desc())
        .limit(1)
    )
    if snap:
        return snap.public_snapshot, snap.etag, snap.version
    data = compiled_defaults()
    etag = 'W/"cfg-default"'
    return data, etag, 0


@public_router.get("/public")
def runtime_public(
    response: Response,
    db: Annotated[Session, Depends(get_db_session)],
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> dict[str, Any] | None:
    snapshot, etag, version = _active_snapshot(db)
    if if_none_match == etag:
        response.status_code = 304
        return None
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=60"
    return {
        "schema_version": snapshot["schema_version"],
        "runtime_version": version,
        "brand": snapshot["brand"],
        "theme": snapshot["theme"],
        "navigation": snapshot["customer_navigation"],
        "content": snapshot["content_templates"],
        "feature_flags": {
            k: bool(v.get("enabled", v.get("safe_default", False)))
            for k, v in snapshot["feature_flags"].items()
        },
        "maintenance": snapshot["maintenance"],
    }


@public_router.post("/flags/evaluate")
def evaluate_flags(
    ctx: RuntimeContext, db: Annotated[Session, Depends(get_db_session)]
) -> dict[str, bool]:
    from vpnsale_domain.configuration import stable_rollout

    snapshot, _, _ = _active_snapshot(db)
    out: dict[str, bool] = {}
    feature_flags = cast(dict[str, Any], snapshot["feature_flags"])
    for code, flag_obj in feature_flags.items():
        if not isinstance(flag_obj, dict):
            continue
        flag = cast(dict[str, Any], flag_obj)
        enabled = bool(flag.get("enabled", flag.get("safe_default", False))) and stable_rollout(
            code, ctx.subject_key, int(flag.get("rollout_percentage", 100))
        )
        if any(not out.get(dep, False) for dep in flag.get("dependencies", [])):
            enabled = False
        out[code] = enabled
    return out


@admin_router.get("/dashboard")
def dashboard(
    admin: Annotated[Any, Depends(current_admin)], db: Annotated[Session, Depends(get_db_session)]
) -> dict[str, Any]:
    if not _permitted(db, admin.id, "configuration.read"):
        raise _err(403, "forbidden")
    snap, etag, ver = _active_snapshot(db)
    return {
        "active_version": ver,
        "etag": etag,
        "schema_version": snap["schema_version"],
        "namespaces": list(snap.keys()),
    }


@admin_router.post("/drafts")
def create_draft(
    body: DraftCreate,
    request: Request,
    admin: Annotated[Any, Depends(current_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    if not _permitted(db, admin.id, "configuration.manage"):
        raise _err(403, "forbidden")
    snapshot = _active_snapshot(db)[0] if body.clone_active else compiled_defaults()
    ref = "draft_" + uuid4().hex[:18]
    row = ConfigurationDraftModel(
        reference=ref,
        status="DRAFT",
        schema_version=1,
        version=1,
        snapshot=snapshot,
        created_by_admin_id=admin.id,
    )
    db.add(row)
    _audit(db, admin.id, "configuration.draft_created", request, {"draft": ref})
    return {"reference": ref, "version": 1, "snapshot": snapshot}


@admin_router.patch("/drafts/{reference}/sections")
def update_section(
    reference: str,
    body: SectionUpdate,
    request: Request,
    admin: Annotated[Any, Depends(current_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    if not _permitted(db, admin.id, "configuration.manage"):
        raise _err(403, "forbidden")
    row = db.scalar(
        select(ConfigurationDraftModel).where(ConfigurationDraftModel.reference == reference)
    )
    if not row or row.status not in {"DRAFT", "VALIDATION_FAILED", "READY_FOR_REVIEW"}:
        raise _err(404, "draft_not_found")
    draft = Draft(reference=row.reference, snapshot=row.snapshot, version=row.version)
    try:
        draft.update_section(body.section, body.value, body.expected_version)
    except ValueError as exc:
        raise _err(409 if str(exc) == "stale_version" else 400, str(exc)) from exc
    result = validate_snapshot(draft.snapshot)
    if not result.ok:
        _security(
            db,
            admin.id,
            "configuration.validation_rejected",
            request,
            {"codes": [i.code for i in result.issues]},
        )
    row.snapshot = draft.snapshot
    row.version = draft.version
    row.status = "DRAFT"
    row.updated_at = datetime.now(UTC)
    _audit(db, admin.id, "configuration.section_changed", request, {"section": body.section})
    return {
        "reference": reference,
        "version": row.version,
        "validation_ok": result.ok,
        "issues": [i.__dict__ for i in result.issues],
    }


@admin_router.post("/drafts/{reference}/validate")
def validate_draft(
    reference: str,
    request: Request,
    admin: Annotated[Any, Depends(current_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    if not _permitted(db, admin.id, "configuration.manage"):
        raise _err(403, "forbidden")
    row = db.scalar(
        select(ConfigurationDraftModel).where(ConfigurationDraftModel.reference == reference)
    )
    if not row:
        raise _err(404, "draft_not_found")
    result = validate_snapshot(row.snapshot)
    row.status = "READY_FOR_REVIEW" if result.ok else "VALIDATION_FAILED"
    db.add(
        ConfigurationValidationRunModel(
            draft_id=row.id,
            status="PASSED" if result.ok else "FAILED",
            issues={"issues": [i.__dict__ for i in result.issues]},
        )
    )
    _audit(db, admin.id, "configuration.validation_run", request, {"ok": result.ok})
    return {"ok": result.ok, "issues": [i.__dict__ for i in result.issues]}


@admin_router.post("/drafts/{reference}/preview")
def preview(
    reference: str,
    body: PreviewCreate,
    request: Request,
    admin: Annotated[Any, Depends(current_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, str]:
    if not _permitted(db, admin.id, "configuration.preview"):
        raise _err(403, "forbidden")
    if not db.scalar(
        select(ConfigurationDraftModel.id).where(ConfigurationDraftModel.reference == reference)
    ):
        raise _err(404, "draft_not_found")
    token = "pv_" + uuid4().hex + uuid4().hex[:8]
    _audit(
        db,
        admin.id,
        "configuration.preview_created",
        request,
        {"channel": body.channel, "expires_minutes": 30},
    )
    return {
        "preview_reference": token,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "warning": "Do not persist or log preview references.",
    }


@admin_router.post("/drafts/{reference}/publish")
def publish_draft(
    reference: str,
    request: Request,
    admin: Annotated[Any, Depends(current_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    if not _permitted(db, admin.id, "configuration.publish"):
        raise _err(403, "forbidden")
    row = db.scalar(
        select(ConfigurationDraftModel).where(ConfigurationDraftModel.reference == reference)
    )
    if not row:
        raise _err(404, "draft_not_found")
    active = db.scalar(
        select(ConfigurationReleaseModel).where(ConfigurationReleaseModel.is_effective.is_(True))
    )
    try:
        rel = publish(
            Draft(reference=row.reference, snapshot=row.snapshot, version=row.version), None
        )
    except ValueError as exc:
        raise _err(400, str(exc)) from exc
    if active:
        db.execute(
            update(ConfigurationReleaseModel)
            .where(ConfigurationReleaseModel.is_effective.is_(True))
            .values(is_effective=False, status="SUPERSEDED")
        )
    release = ConfigurationReleaseModel(
        reference=rel.reference,
        status="PUBLISHED",
        schema_version=1,
        version=(active.version + 1 if active else 1),
        immutable_snapshot=row.snapshot,
        draft_id=row.id,
        published_by_admin_id=admin.id,
        published_at=datetime.now(UTC),
        is_effective=True,
    )
    db.add(release)
    db.flush()
    etag = 'W/"cfg-' + hashlib.sha256(str(row.snapshot).encode()).hexdigest()[:24] + '"'
    db.add(
        RuntimeConfigurationSnapshotModel(
            release_id=release.id, version=release.version, etag=etag, public_snapshot=row.snapshot
        )
    )
    row.status = "PUBLISHED"
    _audit(db, admin.id, "configuration.published", request, {"release": rel.reference})
    return {"release_reference": rel.reference, "version": release.version, "etag": etag}


@admin_router.post("/releases/{reference}/rollback")
def rollback(
    reference: str,
    request: Request,
    admin: Annotated[Any, Depends(current_admin)],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, Any]:
    if not _permitted(db, admin.id, "configuration.rollback"):
        raise _err(403, "forbidden")
    target = db.scalar(
        select(ConfigurationReleaseModel).where(ConfigurationReleaseModel.reference == reference)
    )
    if not target:
        raise _err(404, "release_not_found")
    db.execute(
        update(ConfigurationReleaseModel)
        .where(ConfigurationReleaseModel.is_effective.is_(True))
        .values(is_effective=False, status="ROLLED_BACK")
    )
    clone = ConfigurationReleaseModel(
        reference="rel_rollback_" + uuid4().hex[:12],
        status="PUBLISHED",
        schema_version=1,
        version=target.version + 1,
        immutable_snapshot=target.immutable_snapshot,
        published_by_admin_id=admin.id,
        published_at=datetime.now(UTC),
        is_effective=True,
    )
    db.add(clone)
    db.flush()
    etag = (
        'W/"cfg-' + hashlib.sha256(str(target.immutable_snapshot).encode()).hexdigest()[:24] + '"'
    )
    db.add(
        RuntimeConfigurationSnapshotModel(
            release_id=clone.id,
            version=clone.version,
            etag=etag,
            public_snapshot=target.immutable_snapshot,
        )
    )
    _audit(db, admin.id, "configuration.rollback", request, {"from": reference})
    return {"release_reference": clone.reference, "version": clone.version}
