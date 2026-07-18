from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Final
from uuid import UUID, uuid4


class SupportErrorCode(StrEnum):
    CONVERSATION_FORBIDDEN = "SUPPORT_CONVERSATION_FORBIDDEN"
    STATUS_TRANSITION_INVALID = "SUPPORT_STATUS_TRANSITION_INVALID"
    ASSIGNMENT_CONFLICT = "SUPPORT_ASSIGNMENT_CONFLICT"
    MESSAGE_DUPLICATE = "SUPPORT_MESSAGE_DUPLICATE"
    ATTACHMENT_UNSUPPORTED = "SUPPORT_ATTACHMENT_UNSUPPORTED"
    ATTACHMENT_TOO_LARGE = "SUPPORT_ATTACHMENT_TOO_LARGE"
    ATTACHMENT_QUARANTINED = "SUPPORT_ATTACHMENT_QUARANTINED"
    CSAT_NOT_ELIGIBLE = "SUPPORT_CSAT_NOT_ELIGIBLE"
    CSAT_ALREADY_SUBMITTED = "SUPPORT_CSAT_ALREADY_SUBMITTED"
    MERGE_NOT_ALLOWED = "SUPPORT_MERGE_NOT_ALLOWED"
    TELEGRAM_AGENT_FORBIDDEN = "TELEGRAM_SUPPORT_AGENT_FORBIDDEN"
    BRIDGE_DISABLED = "TELEGRAM_SUPPORT_BRIDGE_DISABLED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class SupportDomainError(ValueError):
    def __init__(self, code: SupportErrorCode, message: str) -> None:
        self.code = code
        super().__init__(message)


class ParticipantType(StrEnum):
    CUSTOMER = "CUSTOMER"
    RESELLER = "RESELLER"
    SUPPORT_AGENT = "SUPPORT_AGENT"
    SUPPORT_MANAGER = "SUPPORT_MANAGER"
    SYSTEM = "SYSTEM"


class SupportChannel(StrEnum):
    CUSTOMER_WEB = "CUSTOMER_WEB"
    TELEGRAM_MINI_APP = "TELEGRAM_MINI_APP"
    TELEGRAM_BOT = "TELEGRAM_BOT"
    RESELLER_WEB = "RESELLER_WEB"
    ADMIN_WEB = "ADMIN_WEB"
    TELEGRAM_SUPPORT_BRIDGE = "TELEGRAM_SUPPORT_BRIDGE"
    SYSTEM_NOTIFICATION = "SYSTEM_NOTIFICATION"


class SupportStatus(StrEnum):
    NEW = "NEW"
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_FOR_CUSTOMER = "WAITING_FOR_CUSTOMER"
    WAITING_FOR_SUPPORT = "WAITING_FOR_SUPPORT"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    SPAM = "SPAM"
    ARCHIVED = "ARCHIVED"


class SupportPriority(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class MessageVisibility(StrEnum):
    PUBLIC = "PUBLIC"
    AGENT_ONLY = "AGENT_ONLY"


class MessageType(StrEnum):
    CUSTOMER_MESSAGE = "CUSTOMER_MESSAGE"
    RESELLER_MESSAGE = "RESELLER_MESSAGE"
    AGENT_MESSAGE = "AGENT_MESSAGE"
    INTERNAL_NOTE = "INTERNAL_NOTE"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    ATTACHMENT = "ATTACHMENT"
    STATUS_EVENT = "STATUS_EVENT"
    ASSIGNMENT_EVENT = "ASSIGNMENT_EVENT"


class AttachmentState(StrEnum):
    QUARANTINED = "QUARANTINED"
    READY = "READY"
    REJECTED = "REJECTED"


ALLOWED_MIME: Final = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain"}
EXECUTABLE_PREFIXES: Final = (b"MZ", b"\x7fELF", b"#!")
SAFE_PLACEHOLDERS: Final = frozenset(
    {
        "customer_display_name",
        "reseller_name",
        "ticket_reference",
        "order_reference",
        "payment_reference",
        "support_agent_name",
        "business_hours",
        "store_name",
    }
)
LEGAL_TRANSITIONS: Final[dict[SupportStatus, set[SupportStatus]]] = {
    SupportStatus.NEW: {
        SupportStatus.OPEN,
        SupportStatus.ASSIGNED,
        SupportStatus.SPAM,
        SupportStatus.CLOSED,
    },
    SupportStatus.OPEN: {
        SupportStatus.ASSIGNED,
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.ESCALATED,
        SupportStatus.CLOSED,
        SupportStatus.SPAM,
    },
    SupportStatus.ASSIGNED: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.ESCALATED,
        SupportStatus.CLOSED,
    },
    SupportStatus.IN_PROGRESS: {
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.WAITING_FOR_SUPPORT,
        SupportStatus.RESOLVED,
        SupportStatus.ESCALATED,
        SupportStatus.CLOSED,
    },
    SupportStatus.WAITING_FOR_CUSTOMER: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.RESOLVED,
        SupportStatus.ESCALATED,
        SupportStatus.CLOSED,
    },
    SupportStatus.WAITING_FOR_SUPPORT: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.ESCALATED,
        SupportStatus.CLOSED,
    },
    SupportStatus.ESCALATED: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_CUSTOMER,
        SupportStatus.RESOLVED,
        SupportStatus.CLOSED,
    },
    SupportStatus.RESOLVED: {SupportStatus.CLOSED, SupportStatus.REOPENED},
    SupportStatus.CLOSED: {SupportStatus.REOPENED, SupportStatus.ARCHIVED},
    SupportStatus.REOPENED: {
        SupportStatus.IN_PROGRESS,
        SupportStatus.WAITING_FOR_SUPPORT,
        SupportStatus.RESOLVED,
        SupportStatus.ESCALATED,
    },
    SupportStatus.SPAM: {SupportStatus.ARCHIVED},
    SupportStatus.ARCHIVED: set(),
}


def _now() -> datetime:
    return datetime.now(UTC)


def sanitize_message(body: str, max_size: int = 4000) -> str:
    normalized = body.replace("\r\n", "\n").strip()
    lowered = normalized.lower()
    if (
        len(normalized) > max_size
        or "<script" in lowered
        or "javascript:" in lowered
        or "<iframe" in lowered
    ):
        raise SupportDomainError(
            SupportErrorCode.IDEMPOTENCY_CONFLICT, "Unsafe or oversized support message"
        )
    return normalized


@dataclass(frozen=True)
class Actor:
    actor_id: UUID
    participant_type: ParticipantType
    tenant_id: UUID | None = None
    permissions: frozenset[str] = frozenset()


@dataclass
class SlaClock:
    first_response_deadline: datetime
    next_response_deadline: datetime
    resolution_deadline: datetime
    paused_at: datetime | None = None
    first_responded_at: datetime | None = None
    breached: set[str] = field(default_factory=set)

    def pause(self, at: datetime) -> None:
        if self.paused_at is None:
            self.paused_at = at

    def resume(self, at: datetime) -> None:
        if self.paused_at is None:
            return
        delta = at - self.paused_at
        self.first_response_deadline += delta
        self.next_response_deadline += delta
        self.resolution_deadline += delta
        self.paused_at = None

    def mark_first_response(self, at: datetime) -> None:
        if self.first_responded_at is None:
            self.first_responded_at = at


@dataclass
class SupportMessage:
    message_id: UUID
    sequence: int
    sender: Actor
    channel: SupportChannel
    message_type: MessageType
    body: str
    visibility: MessageVisibility
    idempotency_key: str
    created_at: datetime = field(default_factory=_now)
    redacted_at: datetime | None = None
    revisions: list[str] = field(default_factory=list)


@dataclass
class SupportConversation:
    conversation_id: UUID
    reference: str
    requester: Actor
    channel: SupportChannel
    category_code: str
    queue_code: str
    subject: str
    priority: SupportPriority = SupportPriority.NORMAL
    status: SupportStatus = SupportStatus.NEW
    assigned_agent_id: UUID | None = None
    version: int = 1
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    messages: list[SupportMessage] = field(default_factory=list)
    idempotency_keys: set[str] = field(default_factory=set)
    assignment_history: list[tuple[datetime, UUID | None, UUID | None, str]] = field(
        default_factory=list
    )
    status_history: list[tuple[datetime, SupportStatus, SupportStatus, str]] = field(
        default_factory=list
    )
    sla: SlaClock | None = None
    csat_cycles: set[int] = field(default_factory=set)
    reopen_cycle: int = 0
    merged_into: UUID | None = None

    @classmethod
    def create(
        cls,
        requester: Actor,
        channel: SupportChannel,
        category_code: str,
        queue_code: str,
        subject: str,
        idempotency_key: str,
    ) -> SupportConversation:
        if requester.participant_type not in {ParticipantType.CUSTOMER, ParticipantType.RESELLER}:
            raise SupportDomainError(
                SupportErrorCode.CONVERSATION_FORBIDDEN,
                "Only customers and resellers create requester conversations",
            )
        digest = sha256(f"{requester.actor_id}:{idempotency_key}".encode()).hexdigest()[:10].upper()
        now = _now()
        return cls(
            uuid4(),
            f"SUP-{digest}",
            requester,
            channel,
            category_code,
            queue_code,
            sanitize_message(subject, 240),
            sla=SlaClock(
                now + timedelta(minutes=30), now + timedelta(hours=4), now + timedelta(days=2)
            ),
            idempotency_keys={idempotency_key},
        )

    def assert_participant(self, actor: Actor) -> None:
        if actor.participant_type in {
            ParticipantType.SUPPORT_AGENT,
            ParticipantType.SUPPORT_MANAGER,
        }:
            if "support.read" not in actor.permissions:
                raise SupportDomainError(
                    SupportErrorCode.CONVERSATION_FORBIDDEN, "Agent lacks support.read"
                )
            return
        if (
            actor.actor_id != self.requester.actor_id
            or actor.participant_type != self.requester.participant_type
            or actor.tenant_id != self.requester.tenant_id
        ):
            raise SupportDomainError(
                SupportErrorCode.CONVERSATION_FORBIDDEN, "Requester isolation violation"
            )

    def transition(
        self, actor: Actor, to_status: SupportStatus, reason: str, expected_version: int
    ) -> None:
        self.assert_participant(actor)
        if expected_version != self.version:
            raise SupportDomainError(
                SupportErrorCode.IDEMPOTENCY_CONFLICT, "Concurrent modification"
            )
        if to_status not in LEGAL_TRANSITIONS[self.status]:
            raise SupportDomainError(
                SupportErrorCode.STATUS_TRANSITION_INVALID, "Illegal support transition"
            )
        if (
            to_status in {SupportStatus.SPAM, SupportStatus.ESCALATED}
            and "support.manage_status" not in actor.permissions
        ):
            raise SupportDomainError(
                SupportErrorCode.CONVERSATION_FORBIDDEN, "Privileged status requires permission"
            )
        previous = self.status
        self.status = to_status
        now = _now()
        if to_status == SupportStatus.WAITING_FOR_CUSTOMER and self.sla:
            self.sla.pause(now)
        if previous == SupportStatus.WAITING_FOR_CUSTOMER and self.sla:
            self.sla.resume(now)
        if to_status == SupportStatus.RESOLVED:
            self.resolved_at = now
        if to_status == SupportStatus.CLOSED:
            self.closed_at = now
        if to_status == SupportStatus.REOPENED:
            self.reopen_cycle += 1
            self.resolved_at = None
            self.closed_at = None
        self.version += 1
        self.updated_at = now
        self.status_history.append((now, previous, to_status, sanitize_message(reason, 500)))

    def claim(self, actor: Actor, expected_version: int) -> None:
        if "support.assign" not in actor.permissions:
            raise SupportDomainError(
                SupportErrorCode.CONVERSATION_FORBIDDEN, "Missing support.assign"
            )
        if expected_version != self.version:
            raise SupportDomainError(
                SupportErrorCode.IDEMPOTENCY_CONFLICT, "Concurrent modification"
            )
        if self.assigned_agent_id and self.assigned_agent_id != actor.actor_id:
            raise SupportDomainError(
                SupportErrorCode.ASSIGNMENT_CONFLICT, "Conversation already claimed"
            )
        old = self.assigned_agent_id
        self.assigned_agent_id = actor.actor_id
        self.assignment_history.append((_now(), old, actor.actor_id, "CLAIM"))
        if self.status in {SupportStatus.NEW, SupportStatus.OPEN}:
            self.status = SupportStatus.ASSIGNED
        self.version += 1

    def send_message(
        self,
        actor: Actor,
        channel: SupportChannel,
        body: str,
        idempotency_key: str,
        internal: bool = False,
    ) -> SupportMessage:
        self.assert_participant(actor)
        if idempotency_key in self.idempotency_keys:
            raise SupportDomainError(
                SupportErrorCode.MESSAGE_DUPLICATE, "Duplicate support message"
            )
        if internal and "support.internal_notes.manage" not in actor.permissions:
            raise SupportDomainError(
                SupportErrorCode.CONVERSATION_FORBIDDEN, "Missing internal note permission"
            )
        visibility = MessageVisibility.AGENT_ONLY if internal else MessageVisibility.PUBLIC
        kind = (
            MessageType.INTERNAL_NOTE
            if internal
            else (
                MessageType.AGENT_MESSAGE
                if actor.participant_type
                in {ParticipantType.SUPPORT_AGENT, ParticipantType.SUPPORT_MANAGER}
                else MessageType.RESELLER_MESSAGE
                if actor.participant_type == ParticipantType.RESELLER
                else MessageType.CUSTOMER_MESSAGE
            )
        )
        msg = SupportMessage(
            uuid4(),
            len(self.messages) + 1,
            actor,
            channel,
            kind,
            sanitize_message(body),
            visibility,
            idempotency_key,
        )
        self.messages.append(msg)
        self.idempotency_keys.add(idempotency_key)
        self.version += 1
        if kind == MessageType.AGENT_MESSAGE and self.sla:
            self.sla.mark_first_response(msg.created_at)
        return msg

    def public_messages_for(self, actor: Actor) -> list[SupportMessage]:
        self.assert_participant(actor)
        if (
            actor.participant_type
            in {ParticipantType.SUPPORT_AGENT, ParticipantType.SUPPORT_MANAGER}
            and "support.internal_notes.read" in actor.permissions
        ):
            return list(self.messages)
        return [m for m in self.messages if m.visibility == MessageVisibility.PUBLIC]

    def submit_csat(self, actor: Actor, score: int, feedback: str | None) -> None:
        self.assert_participant(actor)
        if self.status not in {SupportStatus.RESOLVED, SupportStatus.CLOSED}:
            raise SupportDomainError(
                SupportErrorCode.CSAT_NOT_ELIGIBLE, "CSAT requires resolved or closed conversation"
            )
        if self.reopen_cycle in self.csat_cycles:
            raise SupportDomainError(
                SupportErrorCode.CSAT_ALREADY_SUBMITTED, "CSAT already submitted for cycle"
            )
        if not 1 <= score <= 5:
            raise SupportDomainError(SupportErrorCode.CSAT_NOT_ELIGIBLE, "CSAT score must be 1-5")
        if feedback:
            sanitize_message(feedback, 800)
        self.csat_cycles.add(self.reopen_cycle)


def validate_attachment(
    filename: str, content_type: str, data: bytes, max_bytes: int = 5_000_000
) -> AttachmentState:
    lowered = filename.lower()
    if len(data) > max_bytes:
        raise SupportDomainError(
            SupportErrorCode.ATTACHMENT_TOO_LARGE, "Support attachment too large"
        )
    if content_type not in ALLOWED_MIME or lowered.endswith(
        (".exe", ".js", ".html", ".zip", ".sh")
    ):
        raise SupportDomainError(
            SupportErrorCode.ATTACHMENT_UNSUPPORTED, "Unsupported support attachment"
        )
    if data.startswith(EXECUTABLE_PREFIXES) or b"<script" in data[:4096].lower():
        return AttachmentState.QUARANTINED
    if content_type == "application/pdf" and not data.startswith(b"%PDF-"):
        return AttachmentState.QUARANTINED
    if content_type == "image/png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return AttachmentState.QUARANTINED
    return AttachmentState.READY


def render_canned_response(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key in values:
        if key not in SAFE_PLACEHOLDERS:
            raise SupportDomainError(
                SupportErrorCode.IDEMPOTENCY_CONFLICT, "Unsupported placeholder"
            )
    for key in SAFE_PLACEHOLDERS:
        rendered = rendered.replace("{" + key + "}", values.get(key, ""))
    return sanitize_message(rendered)


def merge_conversations(
    primary: SupportConversation, secondary: SupportConversation, actor: Actor, reason: str
) -> None:
    if "support.merge" not in actor.permissions:
        raise SupportDomainError(
            SupportErrorCode.CONVERSATION_FORBIDDEN, "Missing merge permission"
        )
    if primary.requester != secondary.requester:
        raise SupportDomainError(
            SupportErrorCode.MERGE_NOT_ALLOWED, "Only same requester/tenant can be merged"
        )
    secondary.merged_into = primary.conversation_id
    previous = secondary.status
    secondary.status = SupportStatus.ARCHIVED
    secondary.version += 1
    secondary.updated_at = _now()
    secondary.status_history.append(
        (secondary.updated_at, previous, SupportStatus.ARCHIVED, sanitize_message(reason, 500))
    )
