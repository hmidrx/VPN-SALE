"""Durable canned-response and macro productivity workflows for support agents."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from vpnsale_domain.identity import sanitize_metadata
from vpnsale_domain.support import (
    LEGAL_TRANSITIONS,
    SupportDomainError,
    SupportStatus,
    sanitize_message,
)

from platform_api.database import get_db_session
from platform_api.identity.models import AdminModel, AuditLogModel
from platform_api.management import require_perm
from platform_api.support_runtime_models import (
    support_canned_responses,
    support_conversations,
    support_macros,
)

router = APIRouter(prefix="/api/v1/admin/support-runtime", tags=["admin-support-productivity"])

_CODE_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_LOCALE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
_PLACEHOLDER_RE = re.compile(r"\{\{([a-z][a-z0-9_]{0,63})\}\}")
_PLACEHOLDER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BUILTIN_PLACEHOLDERS = frozenset({"ticket_reference", "subject", "status", "priority"})
_REPLY_BLOCKED = frozenset(
    {
        SupportStatus.RESOLVED.value,
        SupportStatus.CLOSED.value,
        SupportStatus.SPAM.value,
        SupportStatus.ARCHIVED.value,
    }
)


class CannedResponseDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="fa", min_length=2, max_length=16)
    queue_id: UUID | None = None
    category_id: UUID | None = None
    placeholders: list[str] = Field(default_factory=list, max_length=20)
    active: bool = True

    @model_validator(mode="after")
    def validate_definition(self) -> CannedResponseDefinition:
        if not _CODE_RE.fullmatch(self.code):
            raise ValueError("invalid canned response code")
        if not _LOCALE_RE.fullmatch(self.locale):
            raise ValueError("invalid locale")
        if len(self.placeholders) != len(set(self.placeholders)):
            raise ValueError("duplicate placeholders")
        if any(not _PLACEHOLDER_NAME_RE.fullmatch(item) for item in self.placeholders):
            raise ValueError("invalid placeholder")
        if set(_PLACEHOLDER_RE.findall(self.body)) != set(self.placeholders):
            raise ValueError("placeholder declaration mismatch")
        return self


class CannedResponseRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=4000)
    locale: str = Field(default="fa", min_length=2, max_length=16)
    queue_id: UUID | None = None
    category_id: UUID | None = None
    placeholders: list[str] = Field(default_factory=list, max_length=20)
    active: bool = True

    @model_validator(mode="after")
    def validate_revision(self) -> CannedResponseRevision:
        if not _LOCALE_RE.fullmatch(self.locale):
            raise ValueError("invalid locale")
        if len(self.placeholders) != len(set(self.placeholders)):
            raise ValueError("duplicate placeholders")
        if any(not _PLACEHOLDER_NAME_RE.fullmatch(item) for item in self.placeholders):
            raise ValueError("invalid placeholder")
        if set(_PLACEHOLDER_RE.findall(self.body)) != set(self.placeholders):
            raise ValueError("placeholder declaration mismatch")
        return self


class RenderCannedResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locale: str = Field(default="fa", min_length=2, max_length=16)
    values: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_values(self) -> RenderCannedResponseRequest:
        if not _LOCALE_RE.fullmatch(self.locale):
            raise ValueError("invalid locale")
        if len(self.values) > 20:
            raise ValueError("too many placeholder values")
        for key, value in self.values.items():
            if not _PLACEHOLDER_NAME_RE.fullmatch(key):
                raise ValueError("invalid placeholder key")
            if key in _BUILTIN_PLACEHOLDERS:
                raise ValueError("built-in placeholders cannot be overridden")
            if len(value) > 240:
                raise ValueError("placeholder value too long")
        return self


class ReplyDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["reply_draft"]
    body: str = Field(min_length=1, max_length=4000)


class InternalNoteDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["internal_note_draft"]
    body: str = Field(min_length=1, max_length=4000)


class StatusDraftAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["status_draft"]
    status: SupportStatus
    reason: str = Field(min_length=3, max_length=500)


MacroAction = Annotated[
    ReplyDraftAction | InternalNoteDraftAction | StatusDraftAction,
    Field(discriminator="type"),
]


class MacroDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=1, max_length=160)
    actions: list[MacroAction] = Field(min_length=1, max_length=3)
    active: bool = True

    @model_validator(mode="after")
    def validate_definition(self) -> MacroDefinition:
        if not _CODE_RE.fullmatch(self.code):
            raise ValueError("invalid macro code")
        _validate_macro_action_set(self.actions)
        return self


class MacroRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    actions: list[MacroAction] = Field(min_length=1, max_length=3)
    active: bool = True

    @model_validator(mode="after")
    def validate_revision(self) -> MacroRevision:
        _validate_macro_action_set(self.actions)
        return self


class MacroPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(gt=0)


def _validate_macro_action_set(actions: list[MacroAction]) -> None:
    kinds = [item.type for item in actions]
    if len(kinds) != len(set(kinds)):
        raise ValueError("macro action types must be unique")
    for action in actions:
        texts: list[str] = []
        if isinstance(action, ReplyDraftAction | InternalNoteDraftAction):
            texts.append(action.body)
        else:
            texts.append(action.reason)
        for text in texts:
            unknown = set(_PLACEHOLDER_RE.findall(text)) - _BUILTIN_PLACEHOLDERS
            if unknown:
                raise ValueError("macros may only use built-in placeholders")


def _macro_action_from_json(raw: object) -> MacroAction:
    if not isinstance(raw, dict):
        raise ValueError("macro action must be an object")
    payload = cast(dict[str, object], raw)
    kind = payload.get("type")
    if kind == "reply_draft":
        return ReplyDraftAction.model_validate(payload)
    if kind == "internal_note_draft":
        return InternalNoteDraftAction.model_validate(payload)
    if kind == "status_draft":
        return StatusDraftAction.model_validate(payload)
    raise ValueError("unsupported macro action type")


def _clean(value: str, limit: int) -> str:
    try:
        cleaned = sanitize_message(value, limit)
    except (SupportDomainError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="support_productivity_text_invalid") from exc
    if not cleaned:
        raise HTTPException(status_code=422, detail="support_productivity_text_invalid")
    return cleaned


def _conversation(db: Session, reference: str) -> Any:
    row = (
        db.execute(
            select(support_conversations).where(support_conversations.c.reference == reference)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return row


def _builtins(conversation: Any) -> dict[str, str]:
    return {
        "ticket_reference": str(conversation["reference"]),
        "subject": str(conversation["subject"]),
        "status": str(conversation["status"]),
        "priority": str(conversation["priority"]),
    }


def _render_text(template: str, values: dict[str, str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], template)


def _latest_canned_rows(db: Session) -> list[Any]:
    rows = (
        db.execute(
            select(support_canned_responses).order_by(
                support_canned_responses.c.code.asc(),
                support_canned_responses.c.locale.asc(),
                support_canned_responses.c.version.desc(),
            )
        )
        .mappings()
        .all()
    )
    latest: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["code"]), str(row["locale"]))
        if key in seen:
            continue
        seen.add(key)
        latest.append(row)
    return latest


def _latest_canned(db: Session, code: str, locale: str, *, lock: bool = False) -> Any | None:
    statement = (
        select(support_canned_responses)
        .where(
            support_canned_responses.c.code == code,
            support_canned_responses.c.locale == locale,
        )
        .order_by(support_canned_responses.c.version.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return db.execute(statement).mappings().one_or_none()


def _latest_macro_rows(db: Session) -> list[Any]:
    rows = (
        db.execute(
            select(support_macros).order_by(
                support_macros.c.code.asc(), support_macros.c.version.desc()
            )
        )
        .mappings()
        .all()
    )
    latest: list[Any] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row["code"])
        if code in seen:
            continue
        seen.add(code)
        latest.append(row)
    return latest


def _latest_macro(db: Session, code: str, *, lock: bool = False) -> Any | None:
    statement = (
        select(support_macros)
        .where(support_macros.c.code == code)
        .order_by(support_macros.c.version.desc())
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    return db.execute(statement).mappings().one_or_none()


def _canned_view(row: Any) -> dict[str, object]:
    raw_placeholders = row["placeholders"]
    placeholders = (
        cast(list[object], raw_placeholders) if isinstance(raw_placeholders, list) else []
    )
    return {
        "code": str(row["code"]),
        "title": str(row["title"]),
        "locale": str(row["locale"]),
        "queue_id": str(row["queue_id"]) if row["queue_id"] is not None else None,
        "category_id": str(row["category_id"]) if row["category_id"] is not None else None,
        "placeholders": [str(item) for item in placeholders],
        "active": bool(row["active"]),
        "version": int(row["version"]),
        "usage_count": int(row["usage_count"]),
    }


def _macro_view(row: Any) -> dict[str, object]:
    raw_actions = row["actions"]
    actions = cast(list[object], raw_actions) if isinstance(raw_actions, list) else []
    return {
        "code": str(row["code"]),
        "title": str(row["title"]),
        "actions": actions,
        "active": bool(row["active"]),
        "version": int(row["version"]),
    }


def _scope_allows(row: Any, conversation: Any) -> bool:
    if row["queue_id"] is not None and str(row["queue_id"]) != str(conversation["queue_id"]):
        return False
    if row["category_id"] is not None and str(row["category_id"]) != str(
        conversation["category_id"]
    ):
        return False
    return True


def _audit(
    db: Session,
    request: Request,
    admin_id: str,
    event_code: str,
    target_type: str,
    target_id: str,
    metadata: dict[str, object],
) -> None:
    db.add(
        AuditLogModel(
            actor_type="admin",
            actor_id=admin_id,
            target_type=target_type,
            target_id=target_id,
            event_code=event_code,
            occurred_at=datetime.now(UTC),
            correlation_id=(
                request.headers.get("x-request-id")
                or request.headers.get("x-correlation-id")
                or "local"
            ),
            metadata_=sanitize_metadata(metadata),
        )
    )


def _normalized_placeholders(values: dict[str, str]) -> dict[str, str]:
    return {key: _clean(value, 240) for key, value in values.items()}


def _render_canned(row: Any, conversation: Any, supplied: dict[str, str]) -> str:
    raw_placeholders = row["placeholders"]
    if not isinstance(raw_placeholders, list):
        raise HTTPException(status_code=500, detail="canned_response_invalid")
    placeholders = cast(list[object], raw_placeholders)
    declared = {str(item) for item in placeholders}
    if set(_PLACEHOLDER_RE.findall(str(row["body"]))) != declared:
        raise HTTPException(status_code=500, detail="canned_response_invalid")
    custom = declared - _BUILTIN_PLACEHOLDERS
    if set(supplied) != custom:
        raise HTTPException(status_code=422, detail="canned_placeholder_values_invalid")
    values = {**_builtins(conversation), **_normalized_placeholders(supplied)}
    return _clean(_render_text(str(row["body"]), values), 4000)


def _insert_canned_revision(
    db: Session,
    *,
    code: str,
    definition: CannedResponseDefinition | CannedResponseRevision,
    version: int,
) -> Any:
    body = _clean(definition.body, 4000)
    title = _clean(definition.title, 160)
    row_id = str(uuid4())
    db.execute(
        support_canned_responses.insert().values(
            id=row_id,
            code=code,
            title=title,
            body=body,
            locale=definition.locale,
            queue_id=str(definition.queue_id) if definition.queue_id is not None else None,
            category_id=(
                str(definition.category_id) if definition.category_id is not None else None
            ),
            placeholders=list(definition.placeholders),
            active=definition.active,
            version=version,
            usage_count=0,
        )
    )
    return (
        db.execute(select(support_canned_responses).where(support_canned_responses.c.id == row_id))
        .mappings()
        .one()
    )


def _serialize_actions(actions: list[MacroAction]) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for action in actions:
        payload = cast(dict[str, object], action.model_dump(mode="json"))
        if "body" in payload:
            payload["body"] = _clean(str(payload["body"]), 4000)
        if "reason" in payload:
            payload["reason"] = _clean(str(payload["reason"]), 500)
        serialized.append(payload)
    return serialized


def _insert_macro_revision(
    db: Session,
    *,
    code: str,
    definition: MacroDefinition | MacroRevision,
    version: int,
) -> Any:
    title = _clean(definition.title, 160)
    row_id = str(uuid4())
    db.execute(
        support_macros.insert().values(
            id=row_id,
            code=code,
            title=title,
            actions=_serialize_actions(definition.actions),
            active=definition.active,
            version=version,
        )
    )
    return db.execute(select(support_macros).where(support_macros.c.id == row_id)).mappings().one()


@router.get("/canned-responses")
def list_canned_responses(
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.canned_responses.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    reference: str | None = None,
    locale: str | None = None,
    include_inactive: bool = False,
) -> dict[str, object]:
    if locale is not None and not _LOCALE_RE.fullmatch(locale):
        raise HTTPException(status_code=422, detail="locale_invalid")
    conversation = _conversation(db, reference) if reference else None
    items: list[dict[str, object]] = []
    for row in _latest_canned_rows(db):
        if not include_inactive and not bool(row["active"]):
            continue
        if locale is not None and str(row["locale"]) != locale:
            continue
        if conversation is not None and not _scope_allows(row, conversation):
            continue
        items.append(_canned_view(row))
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": items}


@router.post("/canned-responses", status_code=201)
def create_canned_response(
    body: CannedResponseDefinition,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.canned_responses.manage"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    if _latest_canned(db, body.code, body.locale) is not None:
        raise HTTPException(status_code=409, detail="canned_response_exists")
    row = _insert_canned_revision(db, code=body.code, definition=body, version=1)
    _audit(
        db,
        request,
        admin.id,
        "support.canned_response.created",
        "support_canned_response",
        str(row["id"]),
        {"code": body.code, "locale": body.locale, "version": 1},
    )
    db.commit()
    return _canned_view(row)


@router.post("/canned-responses/{code}/revisions", status_code=201)
def revise_canned_response(
    code: str,
    body: CannedResponseRevision,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.canned_responses.manage"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    if not _CODE_RE.fullmatch(code):
        raise HTTPException(status_code=422, detail="canned_response_code_invalid")
    current = _latest_canned(db, code, body.locale, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="canned_response_not_found")
    version = int(current["version"]) + 1
    row = _insert_canned_revision(db, code=code, definition=body, version=version)
    _audit(
        db,
        request,
        admin.id,
        "support.canned_response.revised",
        "support_canned_response",
        str(row["id"]),
        {"code": code, "locale": body.locale, "version": version},
    )
    db.commit()
    return _canned_view(row)


@router.post("/conversations/{reference}/canned-responses/{code}/render")
def render_canned_response(
    reference: str,
    code: str,
    body: RenderCannedResponseRequest,
    response: Response,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.canned_responses.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    conversation = _conversation(db, reference)
    row = _latest_canned(db, code, body.locale, lock=True)
    if row is None or not bool(row["active"]) or not _scope_allows(row, conversation):
        raise HTTPException(status_code=404, detail="canned_response_not_found")
    rendered = _render_canned(row, conversation, body.values)
    db.execute(
        update(support_canned_responses)
        .where(support_canned_responses.c.id == row["id"])
        .values(usage_count=support_canned_responses.c.usage_count + 1)
    )
    _audit(
        db,
        request,
        admin.id,
        "support.canned_response.rendered",
        "support_canned_response",
        str(row["id"]),
        {
            "code": str(row["code"]),
            "locale": str(row["locale"]),
            "version": int(row["version"]),
            "ticket_reference": str(conversation["reference"]),
        },
    )
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "code": str(row["code"]),
        "version": int(row["version"]),
        "body": rendered,
    }


@router.get("/macros")
def list_macros(
    response: Response,
    _: Annotated[AdminModel, Depends(require_perm("support.macros.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    include_inactive: bool = False,
) -> dict[str, object]:
    items = [
        _macro_view(row)
        for row in _latest_macro_rows(db)
        if include_inactive or bool(row["active"])
    ]
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": items}


@router.post("/macros", status_code=201)
def create_macro(
    body: MacroDefinition,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.macros.manage"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    if _latest_macro(db, body.code) is not None:
        raise HTTPException(status_code=409, detail="support_macro_exists")
    row = _insert_macro_revision(db, code=body.code, definition=body, version=1)
    _audit(
        db,
        request,
        admin.id,
        "support.macro.created",
        "support_macro",
        str(row["id"]),
        {"code": body.code, "version": 1},
    )
    db.commit()
    return _macro_view(row)


@router.post("/macros/{code}/revisions", status_code=201)
def revise_macro(
    code: str,
    body: MacroRevision,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.macros.manage"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    if not _CODE_RE.fullmatch(code):
        raise HTTPException(status_code=422, detail="support_macro_code_invalid")
    current = _latest_macro(db, code, lock=True)
    if current is None:
        raise HTTPException(status_code=404, detail="support_macro_not_found")
    version = int(current["version"]) + 1
    row = _insert_macro_revision(db, code=code, definition=body, version=version)
    _audit(
        db,
        request,
        admin.id,
        "support.macro.revised",
        "support_macro",
        str(row["id"]),
        {"code": code, "version": version},
    )
    db.commit()
    return _macro_view(row)


@router.post("/conversations/{reference}/macros/{code}/preview")
def preview_macro(
    reference: str,
    code: str,
    body: MacroPreviewRequest,
    response: Response,
    request: Request,
    admin: Annotated[AdminModel, Depends(require_perm("support.macros.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> dict[str, object]:
    conversation = _conversation(db, reference)
    if int(conversation["version"]) != body.expected_version:
        raise HTTPException(status_code=409, detail="ticket_version_conflict")
    row = _latest_macro(db, code)
    if row is None or not bool(row["active"]):
        raise HTTPException(status_code=404, detail="support_macro_not_found")
    raw_actions = row["actions"]
    if not isinstance(raw_actions, list):
        raise HTTPException(status_code=500, detail="support_macro_invalid")
    action_payloads = cast(list[object], raw_actions)
    try:
        actions = [_macro_action_from_json(item) for item in action_payloads]
        _validate_macro_action_set(actions)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="support_macro_invalid") from exc

    variables = _builtins(conversation)
    preview: dict[str, object | None] = {
        "reply_body": None,
        "internal_note_body": None,
        "status": None,
        "status_reason": None,
    }
    current_status = SupportStatus(str(conversation["status"]))
    for action in actions:
        if isinstance(action, ReplyDraftAction):
            if current_status.value in _REPLY_BLOCKED:
                raise HTTPException(status_code=409, detail="ticket_not_replyable")
            preview["reply_body"] = _clean(_render_text(action.body, variables), 4000)
        elif isinstance(action, InternalNoteDraftAction):
            if current_status == SupportStatus.ARCHIVED:
                raise HTTPException(status_code=409, detail="ticket_not_writable")
            preview["internal_note_body"] = _clean(_render_text(action.body, variables), 4000)
        else:
            if action.status not in LEGAL_TRANSITIONS[current_status]:
                raise HTTPException(status_code=409, detail="macro_transition_invalid")
            preview["status"] = action.status.value
            preview["status_reason"] = _clean(_render_text(action.reason, variables), 500)

    _audit(
        db,
        request,
        admin.id,
        "support.macro.previewed",
        "support_macro",
        str(row["id"]),
        {
            "code": str(row["code"]),
            "version": int(row["version"]),
            "ticket_reference": str(conversation["reference"]),
        },
    )
    db.commit()
    response.headers["Cache-Control"] = "private, no-store"
    return {
        "code": str(row["code"]),
        "title": str(row["title"]),
        "version": int(row["version"]),
        "ticket_version": int(conversation["version"]),
        "draft": preview,
    }
