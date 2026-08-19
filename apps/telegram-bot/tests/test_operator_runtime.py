from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.internal_api import AuthoritativePrivateApiError
from telegram_bot.operator_api import OperatorHealth
from telegram_bot.portal import InMemoryCustomerPortal
from telegram_bot.runtime.handlers import IncomingCommand, IncomingUser
from telegram_bot.runtime.operator import OperatorBotCommandHandler


def _material(label: str) -> str:
    return sha256(f"operator-runtime-test-{label}".encode()).hexdigest()


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=_material("bot"),
        mode=BotMode.WEBHOOK,
        webhook_base_url="https://bot.example.test",
        webhook_secret_token=_material("webhook"),
        mini_app_base_url="https://customer.example.test/app",
        mini_app_allowed_hosts=("customer.example.test",),
        rate_limit_secret=_material("rate"),
    )


class OperatorPortalFixture(InMemoryCustomerPortal):
    def __init__(self, *, denied: bool = False) -> None:
        super().__init__()
        self.denied = denied

    def operator_health(self, telegram_user_id: int) -> OperatorHealth:
        _ = telegram_user_id
        if self.denied:
            raise AuthoritativePrivateApiError(403, "operator_access_denied")
        return OperatorHealth(
            status="DEGRADED",
            signals=("OUTBOX_RETRYING", "USAGE_DATA_STALE"),
            worker_state="RUNNING",
            worker_consecutive_failures=0,
            worker_last_seen_age_seconds=4,
            outbox_pending_due=2,
            outbox_retrying=1,
            outbox_failed=0,
            outbox_stale_claims=0,
            fulfillment_retry_pending=0,
            fulfillment_blocked=0,
            fulfillment_operator_review=0,
            fulfillment_failed=0,
            service_operations_in_progress=1,
            service_operations_review_required=0,
            usage_latest_status="PARTIAL",
            usage_degraded_runs_last_hour=1,
            usage_stale_active_accounts=3,
        )


def _command(update_id: int = 1) -> IncomingCommand:
    return IncomingCommand(
        update_id=update_id,
        chat_type="private",
        user=IncomingUser(telegram_user_id=424242, first_name="اپراتور", language_code="fa"),
        command="/ops",
    )


def test_operator_command_renders_only_bounded_health_and_native_refresh() -> None:
    handler = OperatorBotCommandHandler(
        _settings(),
        InMemoryTelegramIdentityService(),
        portal=OperatorPortalFixture(),
    )

    result = handler.handle_command(_command())

    assert len(result.messages) == 1
    message = result.messages[0]
    assert "وضعیت عملیاتی ربات" in message.text
    assert "نیازمند توجه" in message.text
    assert "Outbox آماده ارسال: 2" in message.text
    assert "Usage قدیمی: 3" in message.text
    callbacks = [button.get("callback_data") for row in message.rows for button in row]
    assert "b:v1:retry:ops" in callbacks
    assert all(value is None or len(value.encode()) <= 64 for value in callbacks)
    lowered = message.text.lower()
    for forbidden in (
        "telegram_user_id",
        "customer_id",
        "panel_id",
        "remote_identity",
        "credential",
        "password",
        "token",
        "postgresql://",
    ):
        assert forbidden not in lowered


def test_operator_command_hides_admin_existence_when_authority_is_denied() -> None:
    handler = OperatorBotCommandHandler(
        _settings(),
        InMemoryTelegramIdentityService(),
        portal=OperatorPortalFixture(denied=True),
    )

    result = handler.handle_command(_command())

    assert result.messages[0].text == "این بخش برای حساب شما فعال نیست."
    assert result.messages[0].rows == []
