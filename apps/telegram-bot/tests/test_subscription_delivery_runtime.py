from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.delivery_api import SubscriptionDelivery
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCallback, IncomingUser
from telegram_bot.runtime.subscription_delivery import (
    SecureDeliveryBotCommandHandler,
    privacy_safe_telegram_payload,
)


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"delivery-test-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"delivery-rate-limit").hexdigest(),
    )


def _user() -> IncomingUser:
    return IncomingUser(42, username="customer", first_name="Customer")


def _callback(action: CallbackAction, value: str, update_id: int) -> IncomingCallback:
    return IncomingCallback(
        update_id,
        f"cb-{update_id}",
        "private",
        _user(),
        BotCallback(action, value).pack(),
    )


class DeliveryPortalFake(InMemoryCustomerPortal):
    def __init__(self) -> None:
        super().__init__()
        self.issue_calls = 0
        self.rotate_calls = 0
        self.revoke_calls = 0
        self.return_existing = False

    def service_delivery_ready(self, context: CustomerContext, service_reference: str) -> bool:
        del context
        return service_reference == "svc-a"

    def issue_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery:
        del context, service_reference
        self.issue_calls += 1
        if self.return_existing:
            return SubscriptionDelivery("ACTIVE", False, {})
        return SubscriptionDelivery(
            "ACTIVE",
            True,
            {
                "base64": "https://sub.example.test/subscriptions/secret-first",
                "mihomo": "https://sub.example.test/subscriptions/secret-first/mihomo",
                "sing_box": "https://sub.example.test/subscriptions/secret-first/sing-box",
            },
        )

    def rotate_subscription(
        self, context: CustomerContext, service_reference: str
    ) -> SubscriptionDelivery:
        del context, service_reference
        self.rotate_calls += 1
        return SubscriptionDelivery(
            "ACTIVE",
            True,
            {"base64": "https://sub.example.test/subscriptions/secret-rotated"},
        )

    def revoke_subscription(self, context: CustomerContext, service_reference: str) -> str:
        del context, service_reference
        self.revoke_calls += 1
        return "REVOKED"

    def connection_uri(self, context: CustomerContext, service_reference: str) -> str:
        del context, service_reference
        return "vless://11111111-1111-4111-8111-111111111111@example.test:443?security=tls"


def _handler(portal: DeliveryPortalFake) -> SecureDeliveryBotCommandHandler:
    return SecureDeliveryBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal
    )


def _callback_values(result: object) -> set[str]:
    messages = getattr(result, "messages")
    values: set[str] = set()
    for row in messages[0].rows:
        for button in row:
            data = button.get("callback_data")
            if data:
                values.add(BotCallback.parse(data).action.value)
    return values


def test_service_detail_exposes_delivery_actions_only_when_authoritatively_ready() -> None:
    portal = DeliveryPortalFake()
    handler = _handler(portal)

    active = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 1))
    expired = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-b", 2))

    active_actions = _callback_values(active)
    expired_actions = _callback_values(expired)
    assert CallbackAction.OPEN_SUBSCRIPTION.value in active_actions
    assert CallbackAction.OPEN_CONFIGS.value in active_actions
    assert CallbackAction.OPEN_SUBSCRIPTION.value not in expired_actions
    assert CallbackAction.OPEN_CONFIGS.value not in expired_actions
    assert "secret-first" not in active.messages[0].text


def test_subscription_secret_is_revealed_only_after_explicit_sensitive_action() -> None:
    portal = DeliveryPortalFake()
    handler = _handler(portal)

    detail = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 10))
    issued = handler.handle_callback(_callback(CallbackAction.OPEN_SUBSCRIPTION, "svc-a", 11))

    assert "secret-first" not in detail.messages[0].text
    assert "secret-first" in issued.messages[0].text
    assert portal.issue_calls == 1


def test_existing_subscription_is_not_reconstructed_and_requires_rotation() -> None:
    portal = DeliveryPortalFake()
    portal.return_existing = True
    result = _handler(portal).handle_callback(
        _callback(CallbackAction.OPEN_SUBSCRIPTION, "svc-a", 20)
    )

    assert "قابل بازسازی" in result.messages[0].text
    assert "secret-first" not in result.messages[0].text
    assert CallbackAction.ROTATE_SUBSCRIPTION.value in _callback_values(result)


def test_rotation_returns_only_new_secret_and_explains_bounded_grace() -> None:
    portal = DeliveryPortalFake()
    result = _handler(portal).handle_callback(
        _callback(CallbackAction.ROTATE_SUBSCRIPTION, "svc-a", 30)
    )

    assert portal.rotate_calls == 1
    assert "secret-rotated" in result.messages[0].text
    assert "۵ دقیقه" in result.messages[0].text
    assert "secret-first" not in result.messages[0].text


def test_revoke_requires_explicit_second_confirmation() -> None:
    portal = DeliveryPortalFake()
    handler = _handler(portal)

    first = handler.handle_callback(_callback(CallbackAction.REVOKE_SUBSCRIPTION, "svc-a", 40))
    assert portal.revoke_calls == 0
    assert CallbackAction.CONFIRM_REVOKE_SUBSCRIPTION.value in _callback_values(first)

    confirmed = handler.handle_callback(
        _callback(CallbackAction.CONFIRM_REVOKE_SUBSCRIPTION, "svc-a", 41)
    )
    assert portal.revoke_calls == 1
    assert "لغو شد" in confirmed.messages[0].text


def test_direct_config_is_revealed_only_after_explicit_action() -> None:
    portal = DeliveryPortalFake()
    handler = _handler(portal)

    detail = handler.handle_callback(_callback(CallbackAction.OPEN_SERVICE, "svc-a", 50))
    direct = handler.handle_callback(_callback(CallbackAction.OPEN_CONFIGS, "svc-a", 51))

    assert "vless://" not in detail.messages[0].text
    assert "vless://" in direct.messages[0].text
    assert "11111111-1111" in direct.messages[0].text


def test_message_transport_disables_link_previews_without_mutating_input() -> None:
    original: dict[str, object] = {"chat_id": 42, "text": "https://sub.example.test/secret"}
    secured = privacy_safe_telegram_payload("sendMessage", original)

    assert "link_preview_options" not in original
    assert secured["link_preview_options"] == {"is_disabled": True}
    assert privacy_safe_telegram_payload("answerCallbackQuery", original) == original
