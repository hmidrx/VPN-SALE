from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal, ManualTopup
from telegram_bot.runtime.handlers import IncomingCallback, IncomingReceipt, IncomingUser
from telegram_bot.runtime.native_topup_destination import NativeTopupDestinationBotCommandHandler
from telegram_bot.topup_destination_api import ManualTopupDestination


def settings() -> BotSettings:
    secret = sha256(b"native-topup-destination").hexdigest()
    return BotSettings(
        enabled=True,
        token=secret,
        mini_app_base_url="https://customer.example.test",
        mini_app_allowed_hosts=("customer.example.test",),
        environment="test",
        sensitive_rate_limit=100,
        mutation_rate_limit=100,
        rate_limit_secret=secret,
    )


def callback(update_id: int, action: CallbackAction, value: str = "") -> IncomingCallback:
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        IncomingUser(42),
        BotCallback(action, value).pack(),
    )


def assert_no_web_app(result) -> None:  # type: ignore[no-untyped-def]
    assert all(
        "web_app_url" not in button
        for message in result.messages
        for row in message.rows
        for button in row
    )


class DirectCardPortal(InMemoryCustomerPortal):
    def create_manual_topup(
        self, context: CustomerContext, amount_rial: int, idempotency_key: str
    ) -> ManualTopup:
        request = super().create_manual_topup(context, amount_rial, idempotency_key)
        updated = ManualTopup(
            request.reference,
            request.amount_toman,
            "AWAITING_RECEIPT",
            request.created_at,
        )
        self._manual_topups[request.reference] = updated
        return updated

    def manual_topup_destination_mode(self, context: CustomerContext, reference: str) -> str:
        return "DIRECT_CARD"

    def manual_topup_destination(
        self, context: CustomerContext, reference: str
    ) -> ManualTopupDestination:
        assert reference in self._manual_topups
        return ManualTopupDestination(
            "DIRECT_CARD",
            False,
            "6037-9912-3456-7890",
            "فروشگاه تست",
        )


class SupportOnlyPortal(InMemoryCustomerPortal):
    def manual_topup_destination(
        self, context: CustomerContext, reference: str
    ) -> ManualTopupDestination:
        return ManualTopupDestination("SUPPORT_ONLY", True)


def test_direct_card_topup_shows_destination_and_never_requires_mini_app() -> None:
    portal = DirectCardPortal()
    handler = NativeTopupDestinationBotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=portal
    )

    review = handler.handle_callback(callback(1, CallbackAction.TOP_UP, "250000"))
    assert "250,000 تومان" in review.messages[0].text
    confirm = handler.handle_callback(callback(2, CallbackAction.CONFIRM_TOP_UP))
    assert "6037-9912-3456-7890" in confirm.messages[0].text
    assert "فروشگاه تست" in confirm.messages[0].text
    assert "📎 ارسال فیش" in [button["text"] for row in confirm.messages[0].rows for button in row]
    assert_no_web_app(confirm)

    reference = next(iter(portal._manual_topups))
    detail = handler.handle_callback(callback(3, CallbackAction.OPEN_MANUAL_TOPUP, reference))
    assert "6037-9912-3456-7890" in detail.messages[0].text
    assert_no_web_app(detail)

    handler.handle_callback(callback(4, CallbackAction.SEND_RECEIPT, reference))
    receipt = handler.handle_receipt(
        IncomingReceipt(5, "private", IncomingUser(42), b"safe-image", "image/jpeg")
    )
    assert "فیش دریافت شد" in receipt.messages[0].text
    assert "6037-9912-3456-7890" not in receipt.messages[0].text
    assert_no_web_app(receipt)


def test_support_only_topup_never_exposes_card_data() -> None:
    portal = SupportOnlyPortal()
    handler = NativeTopupDestinationBotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=portal
    )
    handler.handle_callback(callback(10, CallbackAction.TOP_UP, "250000"))
    result = handler.handle_callback(callback(11, CallbackAction.CONFIRM_TOP_UP))
    assert "پشتیبانی" in result.messages[0].text
    assert "شماره کارت:" not in result.messages[0].text
    assert_no_web_app(result)


def test_destination_failure_fails_closed_to_support_without_web_app() -> None:
    class UnavailablePortal(DirectCardPortal):
        def manual_topup_destination(
            self, context: CustomerContext, reference: str
        ) -> ManualTopupDestination:
            raise RuntimeError("destination unavailable")

    portal = UnavailablePortal()
    handler = NativeTopupDestinationBotCommandHandler(
        settings(), InMemoryTelegramIdentityService(), portal=portal
    )
    handler.handle_callback(callback(20, CallbackAction.TOP_UP, "250000"))
    result = handler.handle_callback(callback(21, CallbackAction.CONFIRM_TOP_UP))
    assert "اطلاعات واریز موقتاً قابل نمایش نیست" in result.messages[0].text
    assert "پشتیبانی" in result.messages[0].text
    assert_no_web_app(result)
