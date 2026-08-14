from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.portal import InMemoryCustomerPortal
from telegram_bot.runtime.handlers import BotCommandHandler, IncomingCallback, IncomingUser


def settings() -> BotSettings:
    secret = sha256(b"native-purchase-test").hexdigest()
    return BotSettings(
        enabled=True,
        token=secret,
        mini_app_base_url="https://customer.example.test",
        mini_app_allowed_hosts=("customer.example.test",),
        environment="test",
        mutation_rate_limit=100,
        rate_limit_secret=secret,
    )


def callback(update: int, action: CallbackAction, value: str = "") -> IncomingCallback:
    return IncomingCallback(
        update, f"cb-{update}", "private", IncomingUser(42), BotCallback(action, value).pack()
    )


def test_catalog_review_and_idempotent_confirmation() -> None:
    portal = InMemoryCustomerPortal()
    store = DurableMemoryConversationStore()
    handler = BotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=portal, conversations=store
    )

    catalog = handler.handle_callback(callback(1, CallbackAction.BUY_SERVICE))
    assert "پلن استاندارد" in catalog.messages[0].text
    review = handler.handle_callback(callback(2, CallbackAction.SELECT_PLAN, "basic"))
    assert "بررسی سفارش" in review.messages[0].text
    assert "موجودی کیف پول" in review.messages[0].text

    first = handler.handle_callback(callback(3, CallbackAction.CONFIRM_PURCHASE))
    second = handler.handle_callback(callback(4, CallbackAction.CONFIRM_PURCHASE))
    assert "سفارش پذیرفته شد" in first.messages[0].text
    assert first.messages[0].text == second.messages[0].text
    assert len(portal._purchases) == 1


def test_purchase_state_survives_handler_restart() -> None:
    portal = InMemoryCustomerPortal()
    store = DurableMemoryConversationStore()
    first = BotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=portal, conversations=store
    )
    first.handle_callback(callback(10, CallbackAction.SELECT_PLAN, "basic"))
    restarted = BotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=portal, conversations=store
    )
    result = restarted.handle_callback(callback(11, CallbackAction.CONFIRM_PURCHASE))
    assert "سفارش پذیرفته شد" in result.messages[0].text


def test_stale_purchase_confirmation_fails_closed() -> None:
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService())
    result = handler.handle_callback(callback(20, CallbackAction.CONFIRM_PURCHASE))
    assert "قدیمی" in result.messages[0].text


def test_common_navigation_has_no_meaningless_cancel_or_refresh() -> None:
    rows = BotCommandHandler(settings(), InMemoryTelegramIdentityService()).nav_rows("fa")
    labels = {button["text"] for row in rows for button in row}
    assert "❌ لغو" not in labels
    assert "🔄 بروزرسانی" not in labels
