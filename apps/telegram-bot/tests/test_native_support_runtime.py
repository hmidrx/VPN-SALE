from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingText, IncomingUser
from telegram_bot.runtime.native_support import NativeSupportBotCommandHandler
from telegram_bot.support_api import SupportTicket, SupportTicketMessage


class _SupportPortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        self.support: dict[str, SupportTicket] = {}
        self.create_calls = 0
        self.reply_calls = 0

    def support_tickets(self, context: CustomerContext) -> list[SupportTicket]:
        del context
        return list(self.support.values())

    def support_ticket(self, context: CustomerContext, reference: str) -> SupportTicket | None:
        del context
        return self.support.get(reference)

    def create_support_ticket(
        self,
        context: CustomerContext,
        subject: str,
        message: str,
        idempotency_key: str,
    ) -> SupportTicket:
        del context
        self.create_calls += 1
        reference = f"SUP-{sha256(idempotency_key.encode()).hexdigest()[:24]}"
        if reference not in self.support:
            now = datetime.now(UTC)
            self.support[reference] = SupportTicket(
                reference,
                subject,
                "NEW",
                now,
                now,
                (SupportTicketMessage(1, "CUSTOMER", message, now),),
            )
        return self.support[reference]

    def reply_support_ticket(
        self,
        context: CustomerContext,
        reference: str,
        message: str,
        idempotency_key: str,
    ) -> SupportTicket:
        del context, idempotency_key
        self.reply_calls += 1
        current = self.support[reference]
        now = datetime.now(UTC)
        updated = SupportTicket(
            current.reference,
            current.subject,
            "WAITING_FOR_SUPPORT",
            current.created_at,
            now,
            (*current.messages, SupportTicketMessage(len(current.messages) + 1, "CUSTOMER", message, now)),
        )
        self.support[reference] = updated
        return updated


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"native-support-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"native-support-rate-limit").hexdigest(),
    )


def _user() -> IncomingUser:
    return IncomingUser(42, username="customer", first_name="Customer")


def _callback(action: CallbackAction, value: str = "", update_id: int = 1) -> IncomingCallback:
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        _user(),
        BotCallback(action, value).pack(),
    )


def _handler() -> tuple[NativeSupportBotCommandHandler, _SupportPortal, DurableMemoryConversationStore]:
    portal = _SupportPortal()
    store = DurableMemoryConversationStore()
    handler = NativeSupportBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal, conversations=store
    )
    return handler, portal, store


def test_new_ticket_text_is_not_persisted_in_conversation_state() -> None:
    handler, portal, store = _handler()
    started = handler.handle_callback(_callback(CallbackAction.SUPPORT_NEW, update_id=10))
    assert "موضوع" in started.messages[0].text
    key = handler._conversation_key(_user())
    state = store.get(key, now_utc())
    assert state.conversation_kind == "support"
    assert state.expected_input == "new"
    assert "مشکل اتصال" not in repr(state)

    created = handler.handle_text(
        IncomingText(11, "private", _user(), "مشکل اتصال\nسرویس من وصل نمی‌شود.")
    )
    assert "مشکل اتصال" in created.messages[0].text
    assert portal.create_calls == 1
    cleared = store.get(key, now_utc())
    assert cleared.conversation_kind is None
    assert cleared.expected_input is None
    assert "سرویس من وصل نمی‌شود" not in repr(cleared)


def test_ticket_list_detail_and_reply_are_native() -> None:
    handler, portal, store = _handler()
    handler.handle_callback(_callback(CallbackAction.SUPPORT_NEW, update_id=20))
    created = handler.handle_text(IncomingText(21, "private", _user(), "صورتحساب\nنیاز به بررسی دارد."))
    reference = next(iter(portal.support))
    assert reference[-8:] in created.messages[0].text

    listing = handler.handle_callback(_callback(CallbackAction.SUPPORT_TICKETS, update_id=22))
    assert "صورتحساب" in listing.messages[0].text
    assert any(
        button.get("callback_data") == BotCallback(CallbackAction.SUPPORT_OPEN, reference).pack()
        for row in listing.messages[0].rows
        for button in row
    )

    reply_prompt = handler.handle_callback(
        _callback(CallbackAction.SUPPORT_REPLY, reference, update_id=23)
    )
    assert "پاسخ خود را" in reply_prompt.messages[0].text
    state = store.get(handler._conversation_key(_user()), now_utc())
    assert state.expected_input == f"reply:{reference}"
    assert "پاسخ جدید" not in repr(state)

    replied = handler.handle_text(IncomingText(24, "private", _user(), "پاسخ جدید مشتری"))
    assert "پاسخ جدید مشتری" in replied.messages[0].text
    assert portal.reply_calls == 1


def test_support_dashboard_replaces_mini_app_placeholder() -> None:
    handler, _portal, _store = _handler()
    result = handler.handle_callback(_callback(CallbackAction.SUPPORT, update_id=30))
    assert "از همین ربات" in result.messages[0].text
    actions = {
        BotCallback.parse(button["callback_data"]).action
        for row in result.messages[0].rows
        for button in row
        if "callback_data" in button
    }
    assert CallbackAction.SUPPORT_NEW in actions
    assert CallbackAction.SUPPORT_TICKETS in actions
