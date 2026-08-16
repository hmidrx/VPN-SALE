from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService, now_utc
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingText, IncomingUser
from telegram_bot.runtime.native_support_csat import NativeSupportCsatBotCommandHandler
from telegram_bot.support_api import (
    SupportCsatState,
    SupportOutcomeUnknown,
    SupportTicket,
    SupportTicketMessage,
    SupportTicketPage,
)

REFERENCE = "SUP-0123456789abcdef01234567"


class _CsatPortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        now = datetime.now(UTC)
        self.ticket = SupportTicket(
            REFERENCE,
            "مشکل اتصال",
            "RESOLVED",
            now,
            now,
            (SupportTicketMessage(1, "SUPPORT_AGENT", "مشکل بررسی و رفع شد.", now),),
        )
        self.csat = SupportCsatState(eligible=True, submitted=False, score=None)
        self.submissions: list[tuple[int, str | None, str]] = []
        self.fail_next = False

    def support_tickets(
        self,
        context: CustomerContext,
        cursor: str | None = None,
        limit: int = 10,
    ) -> SupportTicketPage:
        del context, cursor, limit
        return SupportTicketPage((self.ticket,), None)

    def support_ticket(
        self,
        context: CustomerContext,
        reference: str,
        cursor: str | None = None,
        limit: int = 8,
    ) -> SupportTicket | None:
        del context, cursor, limit
        return self.ticket if reference == REFERENCE else None

    def support_csat_state(self, context: CustomerContext, reference: str) -> SupportCsatState:
        del context
        if reference != REFERENCE:
            raise RuntimeError("missing ticket")
        return self.csat

    def submit_support_csat(
        self,
        context: CustomerContext,
        reference: str,
        score: int,
        feedback: str | None,
        idempotency_key: str,
    ) -> SupportCsatState:
        del context
        assert reference == REFERENCE
        self.submissions.append((score, feedback, idempotency_key))
        if self.fail_next:
            self.fail_next = False
            raise SupportOutcomeUnknown("ambiguous")
        self.csat = SupportCsatState(eligible=False, submitted=True, score=score)
        return self.csat


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"native-support-csat-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"native-support-csat-rate-limit").hexdigest(),
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
    tuple[
        NativeSupportCsatBotCommandHandler,
        _CsatPortal,
        DurableMemoryConversationStore,
    ]
):
    portal = _CsatPortal()
    store = DurableMemoryConversationStore()
    handler = NativeSupportCsatBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal, conversations=store
    )
    return handler, portal, store


def test_resolved_ticket_offers_rating_and_feedback_is_not_persisted_in_state() -> None:
    handler, portal, store = _handler()
    detail = handler.handle_callback(
        _callback(CallbackAction.SUPPORT_OPEN, REFERENCE, update_id=10)
    )
    assert "از پاسخ پشتیبانی راضی بودید" in detail.messages[0].text
    rate_values = {
        BotCallback.parse(button["callback_data"]).value
        for row in detail.messages[0].rows
        for button in row
        if button.get("callback_data")
        and BotCallback.parse(button["callback_data"]).action == CallbackAction.SUPPORT_CSAT_RATE
    }
    assert rate_values == {f"{REFERENCE}|{score}" for score in range(1, 6)}

    prompt = handler.handle_callback(
        _callback(CallbackAction.SUPPORT_CSAT_RATE, f"{REFERENCE}|5", update_id=11)
    )
    assert "امتیاز 5 از ۵" in prompt.messages[0].text
    key = handler._conversation_key(_user())
    state = store.get(key, now_utc())
    assert state.conversation_kind == "support"
    assert state.expected_input == f"csat:{REFERENCE}:5"
    first_key = state.idempotency_key
    assert first_key
    assert "پاسخ خیلی خوب بود" not in repr(state)

    submitted = handler.handle_text(
        IncomingText(12, "private", _user(), "پاسخ خیلی خوب بود و سریع رسید.")
    )
    assert portal.submissions == [(5, "پاسخ خیلی خوب بود و سریع رسید.", first_key)]
    assert "امتیاز ثبت‌شده شما: 5 از ۵" in submitted.messages[0].text
    cleared = store.get(key, now_utc())
    assert cleared.conversation_kind is None
    assert cleared.expected_input is None
    assert cleared.idempotency_key is None
    assert "پاسخ خیلی خوب بود" not in repr(cleared)


def test_csat_can_submit_without_feedback_and_ambiguous_retry_keeps_same_key() -> None:
    handler, portal, store = _handler()
    handler.handle_callback(
        _callback(CallbackAction.SUPPORT_CSAT_RATE, f"{REFERENCE}|4", update_id=20)
    )
    state = store.get(handler._conversation_key(_user()), now_utc())
    stable_key = state.idempotency_key
    assert stable_key
    result = handler.handle_callback(_callback(CallbackAction.SUPPORT_CSAT_SKIP, update_id=21))
    assert portal.submissions == [(4, None, stable_key)]
    assert "امتیاز ثبت‌شده شما: 4 از ۵" in result.messages[0].text

    handler, portal, store = _handler()
    handler.handle_callback(
        _callback(CallbackAction.SUPPORT_CSAT_RATE, f"{REFERENCE}|3", update_id=30)
    )
    portal.fail_next = True
    ambiguous = handler.handle_text(IncomingText(31, "private", _user(), "خوب بود"))
    assert "هنوز مشخص نیست" in ambiguous.messages[0].text
    preserved = store.get(handler._conversation_key(_user()), now_utc())
    preserved_key = preserved.idempotency_key
    assert preserved.expected_input == f"csat:{REFERENCE}:3"
    assert preserved_key

    retried = handler.handle_text(IncomingText(32, "private", _user(), "خوب بود"))
    assert "امتیاز ثبت‌شده شما: 3 از ۵" in retried.messages[0].text
    assert [item[2] for item in portal.submissions] == [preserved_key, preserved_key]
