from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from vpnsale_domain.support import (
    Actor,
    AttachmentState,
    ParticipantType,
    SupportChannel,
    SupportConversation,
    SupportDomainError,
    SupportPriority,
    SupportStatus,
    merge_conversations,
    render_canned_response,
    validate_attachment,
)


def customer(tenant: UUID | None = None) -> Actor:
    return Actor(uuid4(), ParticipantType.CUSTOMER, tenant)


def reseller(tenant: UUID) -> Actor:
    return Actor(uuid4(), ParticipantType.RESELLER, tenant)


def agent(*perms: str) -> Actor:
    return Actor(uuid4(), ParticipantType.SUPPORT_AGENT, permissions=frozenset(perms))


def test_customer_reseller_isolation_and_internal_notes_privacy():
    c = customer()
    a = agent(
        "support.read",
        "support.assign",
        "support.internal_notes.manage",
        "support.internal_notes.read",
    )
    conv = SupportConversation.create(
        c, SupportChannel.CUSTOMER_WEB, "GENERAL", "DEFAULT", "سلام", "create-1"
    )
    conv.claim(a, conv.version)
    conv.send_message(c, SupportChannel.CUSTOMER_WEB, "پیام مشتری", "m1")
    conv.send_message(a, SupportChannel.ADMIN_WEB, "یادداشت داخلی", "n1", internal=True)
    assert [m.body for m in conv.public_messages_for(c)] == ["پیام مشتری"]
    assert len(conv.public_messages_for(a)) == 2
    with pytest.raises(SupportDomainError):
        conv.public_messages_for(customer())


def test_idempotent_ordered_messages_and_duplicate_rejection():
    c = customer()
    conv = SupportConversation.create(
        c, SupportChannel.TELEGRAM_MINI_APP, "PAYMENT", "BILLING", "پرداخت", "create-1"
    )
    first = conv.send_message(c, SupportChannel.TELEGRAM_MINI_APP, "اول", "telegram-update-10")
    second = conv.send_message(c, SupportChannel.TELEGRAM_MINI_APP, "دوم", "telegram-update-11")
    assert (first.sequence, second.sequence) == (1, 2)
    with pytest.raises(SupportDomainError) as exc:
        conv.send_message(c, SupportChannel.TELEGRAM_MINI_APP, "تکراری", "telegram-update-11")
    assert exc.value.code == "SUPPORT_MESSAGE_DUPLICATE"


def test_assignment_conflict_and_legal_transitions():
    c = customer()
    a1 = agent("support.read", "support.assign", "support.manage_status")
    a2 = agent("support.read", "support.assign")
    conv = SupportConversation.create(
        c, SupportChannel.CUSTOMER_WEB, "ORDER", "OPS", "سفارش", "create"
    )
    conv.claim(a1, conv.version)
    with pytest.raises(SupportDomainError):
        conv.claim(a2, conv.version)
    conv.transition(a1, SupportStatus.IN_PROGRESS, "شروع", conv.version)
    conv.transition(a1, SupportStatus.WAITING_FOR_CUSTOMER, "نیاز به پاسخ", conv.version)
    assert conv.sla is not None and conv.sla.paused_at is not None
    conv.transition(a1, SupportStatus.IN_PROGRESS, "پاسخ رسید", conv.version)
    assert conv.sla.paused_at is None
    conv.transition(a1, SupportStatus.RESOLVED, "حل شد", conv.version)
    with pytest.raises(SupportDomainError):
        conv.transition(a1, SupportStatus.SPAM, "بعد از حل", conv.version)


def test_attachment_validation_quarantine_and_rejection():
    assert (
        validate_attachment("shot.png", "image/png", b"\x89PNG\r\n\x1a\nabc")
        == AttachmentState.READY
    )
    assert (
        validate_attachment("bad.pdf", "application/pdf", b"not a pdf")
        == AttachmentState.QUARANTINED
    )
    assert validate_attachment("evil.txt", "text/plain", b"MZ...") == AttachmentState.QUARANTINED
    with pytest.raises(SupportDomainError):
        validate_attachment("run.js", "application/javascript", b"alert(1)")


def test_canned_response_placeholders_escape_and_forbid_unknown():
    assert (
        render_canned_response(
            "سلام {customer_display_name} / {ticket_reference}",
            {"customer_display_name": "مریم", "ticket_reference": "SUP-1"},
        )
        == "سلام مریم / SUP-1"
    )
    with pytest.raises(SupportDomainError):
        render_canned_response("{env.SECRET}", {"env.SECRET": "x"})


def test_csat_once_per_resolution_cycle_and_reopen():
    c = customer()
    a = agent("support.read", "support.assign")
    conv = SupportConversation.create(
        c, SupportChannel.CUSTOMER_WEB, "GENERAL", "DEFAULT", "کمک", "create"
    )
    conv.claim(a, conv.version)
    conv.transition(a, SupportStatus.IN_PROGRESS, "start", conv.version)
    conv.transition(a, SupportStatus.RESOLVED, "done", conv.version)
    conv.submit_csat(c, 5, "خوب")
    with pytest.raises(SupportDomainError):
        conv.submit_csat(c, 4, None)
    conv.transition(c, SupportStatus.REOPENED, "بازگشایی", conv.version)
    conv.transition(a, SupportStatus.IN_PROGRESS, "again", conv.version)
    conv.transition(a, SupportStatus.RESOLVED, "done again", conv.version)
    conv.submit_csat(c, 4, None)


def test_merge_requires_same_requester_and_permission():
    tenant = uuid4()
    r = reseller(tenant)
    a = agent("support.read", "support.merge")
    p = SupportConversation.create(
        r, SupportChannel.RESELLER_WEB, "RESELLER", "PARTNERS", "الف", "p"
    )
    s = SupportConversation.create(r, SupportChannel.RESELLER_WEB, "RESELLER", "PARTNERS", "ب", "s")
    merge_conversations(p, s, a, "duplicate")
    assert s.merged_into == p.conversation_id
    other = SupportConversation.create(
        reseller(uuid4()), SupportChannel.RESELLER_WEB, "RESELLER", "PARTNERS", "ج", "o"
    )
    with pytest.raises(SupportDomainError):
        merge_conversations(p, other, a, "bad")


def test_no_frontend_sla_calculation_clock_is_backend_utc():
    c = customer()
    conv = SupportConversation.create(
        c, SupportChannel.CUSTOMER_WEB, "GENERAL", "DEFAULT", "زمان", "create"
    )
    assert conv.priority == SupportPriority.NORMAL
    assert conv.sla is not None
    assert conv.sla.first_response_deadline.tzinfo == UTC
    assert isinstance(datetime.now(UTC), datetime)
