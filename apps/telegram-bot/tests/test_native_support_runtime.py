from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingText, IncomingUser
from telegram_bot.runtime.native_support import NativeSupportBotCommandHandler
from telegram_bot.support_api import SupportTicket, SupportTicketMessage, SupportTicketPage


class _SupportPortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        self.support: dict[str, SupportTicket] = {}
        self.create_calls = 0
        self.reply_calls = 0

    def support_tickets(
        self,
        context: CustomerContext,
        cursor: str | None = None,
        limit: int = 10,
    ) -> SupportTicketPage:
        del context
        ordered = sorted(self.support.values(), key=lambda ticket: ticket.updated_at, reverse=True)
        offset = int(cursor.removeprefix("tickets:")) if cursor else 0
        items = ordered[offset : offset + limit]
        next_offset = offset + len(items)
        next_cursor = f"tickets:{next_offset}" if next_offset < len(ordered) else None
        return SupportTicketPage(tuple(items), next_cursor)

    def support_ticket(
        self,
        context: CustomerContext,
        reference: str,
        cursor: str | None = None,
        limit: int = 8,
    ) -> SupportTicket | None:
        del context
        current = self.support.get(reference)
        if current is None:
            return None
        before_sequence = int(cursor.removeprefix("messages:")) if cursor else None
        eligible = [
            message
            for message in current.messages
            if before_sequence is None or message.sequence < before_sequence
        ]
        selected = eligible[-limit:]
        next_cursor = (
            f"messages:{selected[0].sequence}"
            if selected and len(eligible) > len(selected)
            else None
        )
        return SupportTicket(
            current.reference,
            current.subject,
            current.status,
            current.created_at,
            current.updated_at,
            tuple(selected),
            next_cursor,
        )

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
            (
                *current.messages,
                SupportTicketMessage(len(current.messages) + 1, "CUSTOMER", message, now),
            ),
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


def _handler() -> (
    tuple[NativeSupportBotCommandHandler, _SupportPortal, DurableMemoryConversationStore]
):
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
    created = handler.handle_text(
        IncomingText(21, "private", _user(), "صورتحساب\nنیاز به بررسی دارد.")
    )
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


def test_ticket_pagination_keeps_opaque_cursor_out_of_callbacks() -> None:
    handler, portal, store = _handler()
    base = datetime.now(UTC)
    for index in range(13):
        reference = f"SUP-{index:024x}"
        at = base + timedelta(minutes=index)
        portal.support[reference] = SupportTicket(
            reference,
            f"تیکت {index}",
            "OPEN",
            at,
            at,
        )

    first = handler.handle_callback(_callback(CallbackAction.SUPPORT_TICKETS, update_id=40))
    assert "تیکت 12" in first.messages[0].text
    assert "تیکت 2" not in first.messages[0].text
    next_callback = BotCallback(CallbackAction.SUPPORT_TICKETS_NEXT).pack()
    assert any(
        button.get("callback_data") == next_callback
        for row in first.messages[0].rows
        for button in row
    )
    key = handler._conversation_key(_user())
    first_state = store.get(key, now_utc())
    assert first_state.support_ticket_next_cursor == "tickets:10"
    assert all("tickets:10" not in str(button) for row in first.messages[0].rows for button in row)

    second = handler.handle_callback(_callback(CallbackAction.SUPPORT_TICKETS_NEXT, update_id=41))
    assert "تیکت 2" in second.messages[0].text
    assert any(
        button.get("callback_data") == BotCallback(CallbackAction.SUPPORT_TICKETS_PREV).pack()
        for row in second.messages[0].rows
        for button in row
    )
    second_state = store.get(key, now_utc())
    assert second_state.support_ticket_cursor == "tickets:10"
    assert second_state.support_ticket_previous_cursors == ("",)

    first_again = handler.handle_callback(
        _callback(CallbackAction.SUPPORT_TICKETS_PREV, update_id=42)
    )
    assert "تیکت 12" in first_again.messages[0].text
    assert store.get(key, now_utc()).support_ticket_cursor is None


def test_message_history_pages_are_reversible_without_body_in_state() -> None:
    handler, portal, store = _handler()
    reference = "SUP-aaaaaaaaaaaaaaaaaaaaaaaa"
    base = datetime.now(UTC)
    messages = tuple(
        SupportTicketMessage(
            sequence=index,
            sender_type="CUSTOMER" if index % 2 else "SUPPORT_AGENT",
            body=f"history body {index}",
            created_at=base + timedelta(minutes=index),
        )
        for index in range(1, 18)
    )
    portal.support[reference] = SupportTicket(
        reference,
        "تاریخچه طولانی",
        "OPEN",
        base,
        base + timedelta(minutes=17),
        messages,
    )

    latest = handler.handle_callback(
        _callback(CallbackAction.SUPPORT_OPEN, reference, update_id=50)
    )
    assert "history body 17" in latest.messages[0].text
    assert "history body 9" not in latest.messages[0].text
    key = handler._conversation_key(_user())
    state = store.get(key, now_utc())
    assert state.support_message_next_cursor == "messages:10"
    assert "history body" not in repr(state)

    older = handler.handle_callback(_callback(CallbackAction.SUPPORT_MESSAGES_OLDER, update_id=51))
    assert "history body 9" in older.messages[0].text
    assert "history body 2" in older.messages[0].text
    state = store.get(key, now_utc())
    assert state.support_message_cursor == "messages:10"
    assert state.support_message_previous_cursors == ("",)
    assert all("messages:10" not in str(button) for row in older.messages[0].rows for button in row)

    newest = handler.handle_callback(_callback(CallbackAction.SUPPORT_MESSAGES_NEWER, update_id=52))
    assert "history body 17" in newest.messages[0].text
    assert store.get(key, now_utc()).support_message_cursor is None


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
