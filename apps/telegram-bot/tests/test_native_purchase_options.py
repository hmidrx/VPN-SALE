from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.portal import InMemoryCustomerPortal, PurchasePlan, PurchaseResult
from telegram_bot.purchase_api import (
    NativePurchaseCatalogItem,
    NativePurchaseChoice,
    NativePurchaseOptions,
    NativePurchaseRange,
)
from telegram_bot.runtime.handlers import IncomingCallback, IncomingText, IncomingUser
from telegram_bot.runtime.native_purchase_options import NativePurchaseBotCommandHandler


def settings() -> BotSettings:
    secret = sha256(b"native-purchase-options").hexdigest()
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


def callback(update: int, action: CallbackAction, value: str = "") -> IncomingCallback:
    return IncomingCallback(
        update,
        f"cb-{update}",
        "private",
        IncomingUser(42),
        BotCallback(action, value).pack(),
    )


def button(result, label: str) -> BotCallback:  # type: ignore[no-untyped-def]
    for row in result.messages[0].rows:
        for item in row:
            if item.get("text") == label:
                return BotCallback.parse(item.get("callback_data"))
    raise AssertionError(f"button not found: {label}")


class NativePortal(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        self.reference = "p_custom123456789"
        self.preview_calls: list[dict[str, int | str]] = []
        self.confirm_calls = 0
        long_prefix = "location_" + ("x" * 68)
        self.options = NativePurchaseOptions(
            self.reference,
            "پلن حرفه‌ای قابل تنظیم",
            True,
            None,
            NativePurchaseRange(10, 100, 10, (10, 20, 50, 100)),
            NativePurchaseRange(30, 180, 30, (30, 60, 90, 180)),
            NativePurchaseRange(1, 5, 1, (1, 2, 3, 5)),
            (
                NativePurchaseChoice("de", "آلمان"),
                NativePurchaseChoice("fr", "فرانسه"),
                NativePurchaseChoice("tr", "ترکیه"),
                NativePurchaseChoice("uk", "انگلیس"),
                NativePurchaseChoice("fi", "فنلاند"),
                NativePurchaseChoice(long_prefix, "لوکیشن طولانی"),
                NativePurchaseChoice("nl", "هلند"),
            ),
            (
                NativePurchaseChoice("standard", "استاندارد"),
                NativePurchaseChoice("gaming", "گیمینگ"),
            ),
        )
        self.results: dict[str, PurchaseResult] = {}

    def native_purchase_catalog(self, context):  # type: ignore[no-untyped-def]
        return [NativePurchaseCatalogItem(self.reference, self.options.title, True, None)]

    def native_purchase_options(self, context, reference):  # type: ignore[no-untyped-def]
        return self.options if reference == self.reference else None

    def native_purchase_preview(self, context, reference, selection):  # type: ignore[no-untyped-def]
        assert reference == self.reference
        self.preview_calls.append(dict(selection))
        traffic = int(selection["traffic_gb"])
        duration = int(selection["duration_days"])
        devices = int(selection["device_count"])
        location = str(selection["location_code"])
        quality = str(selection["quality_code"])
        location_label = next(x.label for x in self.options.locations if x.code == location)
        return PurchasePlan(
            self.reference,
            self.options.title,
            traffic,
            duration,
            devices,
            location,
            location_label,
            quality,
            100_000 + traffic * 1_000 + duration * 100 + devices * 500,
            {
                "traffic_bytes": traffic * 1024**3,
                "duration_days": duration,
                "device_count": devices,
                "location_code": location,
                "quality_code": quality,
            },
        )

    def confirm_purchase(self, context, plan, idempotency_key):  # type: ignore[no-untyped-def]
        if idempotency_key in self.results:
            return self.results[idempotency_key]
        self.confirm_calls += 1
        result = PurchaseResult(
            f"ord_{self.confirm_calls}",
            "ACCEPTED",
            "PROVISIONING",
            plan,
        )
        self.results[idempotency_key] = result
        return result

    def purchase_order(self, context, reference):  # type: ignore[no-untyped-def]
        return next(
            (result for result in self.results.values() if result.order_reference == reference),
            None,
        )


def handler(
    portal: NativePortal | None = None,
) -> tuple[NativePurchaseBotCommandHandler, NativePortal]:
    value = portal or NativePortal()
    return (
        NativePurchaseBotCommandHandler(
            settings(),
            InMemoryTelegramIdentityService(),
            portal=value,
            conversations=DurableMemoryConversationStore(),
        ),
        value,
    )


def test_configurable_plan_is_fully_purchasable_without_mini_app() -> None:
    bot, portal = handler()
    catalog = bot.handle_callback(callback(1, CallbackAction.BUY_SERVICE))
    assert "پلن حرفه‌ای قابل تنظیم" in catalog.messages[0].text
    assert "مینی‌اپ" not in catalog.messages[0].text

    traffic = bot.handle_callback(callback(2, CallbackAction.SELECT_PLAN, portal.reference))
    assert "حجم سرویس" in traffic.messages[0].text
    choice = button(traffic, "20")
    duration = bot.handle_callback(callback(3, choice.action, choice.value))
    assert "مدت سرویس" in duration.messages[0].text
    choice = button(duration, "60")
    devices = bot.handle_callback(callback(4, choice.action, choice.value))
    assert "تعداد دستگاه" in devices.messages[0].text
    choice = button(devices, "2")
    locations = bot.handle_callback(callback(5, choice.action, choice.value))
    assert "موقعیت سرویس" in locations.messages[0].text
    for row in locations.messages[0].rows:
        for item in row:
            data = item.get("callback_data")
            if data:
                assert len(data.encode()) <= 64

    second_page_button = button(locations, "بعدی ▶️")
    second_page = bot.handle_callback(
        callback(6, second_page_button.action, second_page_button.value)
    )
    nl = button(second_page, "هلند")
    qualities = bot.handle_callback(callback(7, nl.action, nl.value))
    assert "کیفیت سرویس" in qualities.messages[0].text
    gaming = button(qualities, "گیمینگ")
    review = bot.handle_callback(callback(8, gaming.action, gaming.value))
    assert "بررسی سفارش" in review.messages[0].text
    assert "هلند" in review.messages[0].text
    assert "20" in review.messages[0].text
    assert "مینی‌اپ" not in review.messages[0].text
    assert portal.preview_calls == [
        {
            "traffic_gb": 20,
            "duration_days": 60,
            "device_count": 2,
            "location_code": "nl",
            "quality_code": "gaming",
        }
    ]

    first = bot.handle_callback(callback(9, CallbackAction.CONFIRM_PURCHASE))
    replay = bot.handle_callback(callback(10, CallbackAction.CONFIRM_PURCHASE))
    assert "سفارش پذیرفته شد" in first.messages[0].text
    assert "سفارش پذیرفته شد" in replay.messages[0].text
    assert portal.confirm_calls == 1


def test_custom_numeric_value_must_match_authoritative_range_step() -> None:
    bot, portal = handler()
    bot.handle_callback(callback(20, CallbackAction.SELECT_PLAN, portal.reference))
    custom = bot.handle_callback(callback(21, CallbackAction.SELECT_PLAN, "ct"))
    assert "مقدار را به عدد ارسال کنید" in custom.messages[0].text

    invalid = bot.handle_text(IncomingText(22, "private", IncomingUser(42), "۳۵"))
    assert "مجاز نیست" in invalid.messages[0].text

    valid = bot.handle_text(IncomingText(23, "private", IncomingUser(42), "۳۰"))
    assert "مدت سرویس" in valid.messages[0].text


def test_long_catalog_option_codes_never_enter_telegram_callback_payload() -> None:
    bot, portal = handler()
    traffic = bot.handle_callback(callback(30, CallbackAction.SELECT_PLAN, portal.reference))
    choice = button(traffic, "20")
    duration = bot.handle_callback(callback(31, choice.action, choice.value))
    choice = button(duration, "60")
    devices = bot.handle_callback(callback(32, choice.action, choice.value))
    choice = button(devices, "2")
    locations = bot.handle_callback(callback(33, choice.action, choice.value))
    all_payloads = [
        item["callback_data"]
        for row in locations.messages[0].rows
        for item in row
        if "callback_data" in item
    ]
    assert all(len(payload.encode()) <= 64 for payload in all_payloads)
    assert not any("location_" in payload for payload in all_payloads)
