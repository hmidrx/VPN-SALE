from __future__ import annotations

from typing import Annotated, NoReturn
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from vpnsale_domain.support import (
    Actor,
    ParticipantType,
    SupportChannel,
    SupportConversation,
    SupportDomainError,
    SupportStatus,
    validate_attachment,
)

customer_router = APIRouter(prefix="/api/v1/customer/support", tags=["customer-support"])
reseller_router = APIRouter(prefix="/api/v1/reseller/support", tags=["reseller-support"])
admin_router = APIRouter(prefix="/api/v1/admin/support", tags=["admin-support"])

CONVERSATIONS: dict[str, SupportConversation] = {}


class ApiError(BaseModel):
    code: str
    message: str


class ConversationCreate(BaseModel):
    category_code: str = Field(min_length=2, max_length=64)
    queue_code: str = Field(min_length=2, max_length=64)
    subject: str = Field(min_length=1, max_length=240)
    channel: SupportChannel


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    channel: SupportChannel
    internal: bool = False


class StatusChange(BaseModel):
    status: SupportStatus
    reason: str = Field(min_length=3, max_length=500)
    expected_version: int


class ConversationOut(BaseModel):
    reference: str
    requester_type: str
    channel: str
    category_code: str
    queue_code: str
    subject: str
    status: str
    priority: str
    assigned_agent_id: str | None
    version: int
    first_response_deadline: str | None
    resolution_deadline: str | None


class MessageOut(BaseModel):
    sequence: int
    sender_type: str
    channel: str
    message_type: str
    visibility: str
    body: str
    created_at: str


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class AttachmentCheck(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(min_length=3, max_length=100)
    content_hex_prefix: str = Field(min_length=0, max_length=128)
    byte_size: int = Field(ge=0, le=5_000_000)


class AttachmentStatus(BaseModel):
    state: str
    asset_reference: str


def _customer_actor(value: str | None) -> Actor:
    return Actor(UUID(value) if value else uuid4(), ParticipantType.CUSTOMER)


def _reseller_actor(user: str | None, tenant: str | None) -> Actor:
    return Actor(
        UUID(user) if user else uuid4(), ParticipantType.RESELLER, UUID(tenant) if tenant else None
    )


def _agent_actor(value: str | None, permissions: str | None) -> Actor:
    return Actor(
        UUID(value) if value else uuid4(),
        ParticipantType.SUPPORT_AGENT,
        permissions=frozenset(p.strip() for p in (permissions or "").split(",") if p.strip()),
    )


def _out(conv: SupportConversation, actor: Actor) -> ConversationDetail:
    return ConversationDetail(
        reference=conv.reference,
        requester_type=conv.requester.participant_type.value,
        channel=conv.channel.value,
        category_code=conv.category_code,
        queue_code=conv.queue_code,
        subject=conv.subject,
        status=conv.status.value,
        priority=conv.priority.value,
        assigned_agent_id=str(conv.assigned_agent_id) if conv.assigned_agent_id else None,
        version=conv.version,
        first_response_deadline=conv.sla.first_response_deadline.isoformat() if conv.sla else None,
        resolution_deadline=conv.sla.resolution_deadline.isoformat() if conv.sla else None,
        messages=[
            MessageOut(
                sequence=m.sequence,
                sender_type=m.sender.participant_type.value,
                channel=m.channel.value,
                message_type=m.message_type.value,
                visibility=m.visibility.value,
                body=m.body,
                created_at=m.created_at.isoformat(),
            )
            for m in conv.public_messages_for(actor)
        ],
    )


def _get(reference: str) -> SupportConversation:
    conv = CONVERSATIONS.get(reference)
    if conv is None:
        raise HTTPException(
            404,
            {"code": "SUPPORT_CONVERSATION_NOT_FOUND", "message": "Support conversation not found"},
        )
    return conv


def _handle(exc: SupportDomainError) -> NoReturn:
    raise HTTPException(
        409 if "DUPLICATE" in exc.code or "CONFLICT" in exc.code else 403,
        {"code": exc.code.value, "message": str(exc)},
    ) from exc


@customer_router.get("/conversations", response_model=list[ConversationOut])
def list_customer_conversations(
    x_customer_id: Annotated[str | None, Header()] = None,
) -> list[ConversationOut]:
    actor = _customer_actor(x_customer_id)
    return [
        _out(c, actor)
        for c in CONVERSATIONS.values()
        if c.requester.actor_id == actor.actor_id
        and c.requester.participant_type == ParticipantType.CUSTOMER
    ]


@customer_router.post(
    "/conversations", response_model=ConversationDetail, responses={403: {"model": ApiError}}
)
def create_customer_conversation(
    body: ConversationCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    x_customer_id: Annotated[str | None, Header()] = None,
) -> ConversationDetail:
    actor = _customer_actor(x_customer_id)
    conv = SupportConversation.create(
        actor, body.channel, body.category_code, body.queue_code, body.subject, idempotency_key
    )
    if conv.reference not in CONVERSATIONS:
        CONVERSATIONS[conv.reference] = conv
    return _out(conv, actor)


@customer_router.get("/conversations/{reference}", response_model=ConversationDetail)
def get_customer_conversation(
    reference: str, x_customer_id: Annotated[str | None, Header()] = None
) -> ConversationDetail:
    actor = _customer_actor(x_customer_id)
    try:
        return _out(_get(reference), actor)
    except SupportDomainError as exc:
        _handle(exc)


@customer_router.post("/conversations/{reference}/messages", response_model=MessageOut)
def send_customer_message(
    reference: str,
    body: MessageCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    x_customer_id: Annotated[str | None, Header()] = None,
) -> MessageOut:
    actor = _customer_actor(x_customer_id)
    try:
        msg = _get(reference).send_message(actor, body.channel, body.body, idempotency_key)
        return MessageOut(
            sequence=msg.sequence,
            sender_type=msg.sender.participant_type.value,
            channel=msg.channel.value,
            message_type=msg.message_type.value,
            visibility=msg.visibility.value,
            body=msg.body,
            created_at=msg.created_at.isoformat(),
        )
    except SupportDomainError as exc:
        _handle(exc)


@customer_router.post("/attachments/check", response_model=AttachmentStatus)
def check_customer_attachment(body: AttachmentCheck) -> AttachmentStatus:
    data = bytes.fromhex(body.content_hex_prefix) + (
        b"0" * max(0, min(body.byte_size, 16) - len(bytes.fromhex(body.content_hex_prefix)))
    )
    try:
        state = validate_attachment(body.filename, body.content_type, data)
    except SupportDomainError as exc:
        _handle(exc)
    return AttachmentStatus(state=state.value, asset_reference=f"sat_{uuid4().hex[:16]}")


@reseller_router.post("/conversations", response_model=ConversationDetail)
def create_reseller_conversation(
    body: ConversationCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    x_reseller_user_id: Annotated[str | None, Header()] = None,
    x_reseller_tenant_id: Annotated[str | None, Header()] = None,
) -> ConversationDetail:
    actor = _reseller_actor(x_reseller_user_id, x_reseller_tenant_id)
    conv = SupportConversation.create(
        actor, body.channel, body.category_code, body.queue_code, body.subject, idempotency_key
    )
    CONVERSATIONS[conv.reference] = conv
    return _out(conv, actor)


@admin_router.get("/inbox", response_model=list[ConversationOut])
def admin_inbox(
    x_admin_id: Annotated[str | None, Header()] = None,
    x_permissions: Annotated[str | None, Header()] = None,
) -> list[ConversationOut]:
    actor = _agent_actor(x_admin_id, x_permissions)
    return [_out(c, actor) for c in CONVERSATIONS.values()]


@admin_router.post("/conversations/{reference}/claim", response_model=ConversationDetail)
def claim(
    reference: str,
    expected_version: int,
    x_admin_id: Annotated[str | None, Header()] = None,
    x_permissions: Annotated[str | None, Header()] = None,
) -> ConversationDetail:
    actor = _agent_actor(x_admin_id, x_permissions)
    try:
        conv = _get(reference)
        conv.claim(actor, expected_version)
        return _out(conv, actor)
    except SupportDomainError as exc:
        _handle(exc)


@admin_router.post("/conversations/{reference}/messages", response_model=MessageOut)
def admin_message(
    reference: str,
    body: MessageCreate,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    x_admin_id: Annotated[str | None, Header()] = None,
    x_permissions: Annotated[str | None, Header()] = None,
) -> MessageOut:
    actor = _agent_actor(x_admin_id, x_permissions)
    try:
        msg = _get(reference).send_message(
            actor, body.channel, body.body, idempotency_key, body.internal
        )
        return MessageOut(
            sequence=msg.sequence,
            sender_type=msg.sender.participant_type.value,
            channel=msg.channel.value,
            message_type=msg.message_type.value,
            visibility=msg.visibility.value,
            body=msg.body,
            created_at=msg.created_at.isoformat(),
        )
    except SupportDomainError as exc:
        _handle(exc)


@admin_router.post("/conversations/{reference}/status", response_model=ConversationDetail)
def admin_status(
    reference: str,
    body: StatusChange,
    x_admin_id: Annotated[str | None, Header()] = None,
    x_permissions: Annotated[str | None, Header()] = None,
) -> ConversationDetail:
    actor = _agent_actor(x_admin_id, x_permissions)
    try:
        conv = _get(reference)
        conv.transition(actor, body.status, body.reason, body.expected_version)
        return _out(conv, actor)
    except SupportDomainError as exc:
        _handle(exc)
