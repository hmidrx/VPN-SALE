from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingReceipt, IncomingUser
from telegram_bot.runtime.native_support_attachments import NativeSupportAttachmentBotCommandHandler
from telegram_bot.support_api import SupportTicket, SupportTicketMessage


class _AttachmentPortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        now = datetime.now(UTC)
        self.ticket = SupportTicket(
            "SUP-aaaaaaaaaaaaaaaaaaaaaaaa",
            "مشکل اتصال",
            "WAITING_FOR_CUSTOMER",
            now,
            now,
            (SupportTicketMessage(1, "CUSTOMER", "متن اولیه", now),),
        )
        self.upload_calls = 0
        self.last_payload: tuple[bytes, str, str] | None = None

    def support_ticket(
        self,
        context: CustomerContext,
        reference: str,
        cursor: str | None = None,
        limit: int = 8,
    ) -> SupportTicket | None:
        del context, cursor, limit
        return self.ticket if reference == self.ticket.reference else None

    def upload_support_attachment(
        self,
        context: CustomerContext,
        reference: str,
        content: bytes,
        content_type: str,
        idempotency_key: str,
    ) -> SupportTicket:
        del context
        assert reference == self.ticket.reference
        self.upload_calls += 1
        self.last_payload = content, content_type, idempotency_key
        now = datetime.now(UTC)
        self.ticket = SupportTicket(
            self.ticket.reference,
            self.ticket.subject,
            "WAITING_FOR_SUPPORT",
            self.ticket.created_at,
            now,
            (
                *self.ticket.messages,
                SupportTicketMessage(2, "CUSTOMER", "📎 تصویر پیوست شد.", now),
            ),
        )
        return self.ticket


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"native-support-attachment-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"native-support-attachment-rate-limit").hexdigest(),
    )


def _user() -> IncomingUser:
    return IncomingUser(42, username="customer", first_name="Customer")


def test_support_attachment_state_is_bounded_and_upload_is_native() -> None:
    portal = _AttachmentPortal()
    store = DurableMemoryConversationStore()
    handler = NativeSupportAttachmentBotCommandHandler(
        _settings(),
        InMemoryTelegramIdentityService(),
        portal=portal,
        conversations=store,
    )
    reference = portal.ticket.reference

    detail = handler._ticket_detail(_user(), "fa", reference)
    attachment_callback = BotCallback(CallbackAction.SUPPORT_ATTACHMENT, reference).pack()
    assert any(
        button.get("callback_data") == attachment_callback
        for row in detail.messages[0].rows
        for button in row
    )

    prompt = handler.handle_callback(
        IncomingCallback(
            100,
            "cb-100",
            "private",
            _user(),
            attachment_callback,
        )
    )
    assert "۵ مگابایت" in prompt.messages[0].text
    key = handler._conversation_key(_user())
    state = store.get(key, now_utc())
    assert state.conversation_kind == "support"
    assert state.expected_input == f"attachment:{reference}"
    assert handler.expected_support_attachment_reference(_user()) == reference
    assert "image" not in repr(state).lower()

    result = handler.handle_support_attachment(
        IncomingReceipt(101, "private", _user(), b"safe-image-bytes", "image/png")
    )
    assert portal.upload_calls == 1
    assert portal.last_payload is not None
    assert portal.last_payload[0] == b"safe-image-bytes"
    assert portal.last_payload[1] == "image/png"
    assert portal.last_payload[2].startswith("tg-support-attachment:100:")
    assert "تصویر پیوست شد" in result.messages[0].text

    cleared = store.get(key, now_utc())
    assert cleared.conversation_kind is None
    assert cleared.expected_input is None
    assert cleared.idempotency_key is None
