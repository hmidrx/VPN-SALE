from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from urllib.error import HTTPError

import pytest

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotSettings
from telegram_bot.conversation import DurableMemoryConversationStore
from telegram_bot.internal_api import (
    AuthoritativePrivateApiError,
    PrivateApiUnavailable,
    PrivatePlatformClient,
    PurchaseOutcomeUnknown,
)
from telegram_bot.portal import InMemoryCustomerPortal, PurchasePlan, PurchaseResult
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


def test_insufficient_wallet_never_attempts_purchase() -> None:
    class PoorPortal(InMemoryCustomerPortal):
        def wallet_balance(self, context):  # type: ignore[no-untyped-def]
            return 10, "IRR"

    portal = PoorPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    result = handler.handle_callback(callback(30, CallbackAction.SELECT_PLAN, "basic"))
    assert "مبلغ کسری" in result.messages[0].text
    assert not portal._purchases


def test_price_change_requires_explicit_second_confirmation() -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(callback(40, CallbackAction.SELECT_PLAN, "basic"))
    old = portal._purchase_plans[0]
    portal._purchase_plans[0] = PurchasePlan(
        old.reference,
        old.title,
        old.traffic_gb,
        old.duration_days,
        old.device_limit,
        old.location_code,
        old.location_label,
        old.quality_code,
        old.price_toman + 50_000,
        old.selection,
    )
    changed = handler.handle_callback(callback(41, CallbackAction.CONFIRM_PURCHASE))
    assert "تغییر کرده است" in changed.messages[0].text
    assert not portal._purchases
    accepted = handler.handle_callback(callback(42, CallbackAction.CONFIRM_PURCHASE))
    assert "سفارش پذیرفته شد" in accepted.messages[0].text
    assert len(portal._purchases) == 1


def test_unavailable_plan_fails_without_wallet_claim() -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(callback(50, CallbackAction.SELECT_PLAN, "basic"))
    portal._purchase_plans.clear()
    result = handler.handle_callback(callback(51, CallbackAction.CONFIRM_PURCHASE))
    assert "موجودی کیف پول شما بدون تغییر" not in result.messages[0].text
    assert "بررسی کنید" in result.messages[0].text


def test_ambiguous_outcome_is_reconciled_with_same_state_key() -> None:
    class AmbiguousPortal(InMemoryCustomerPortal):
        attempts: list[str] = []

        def confirm_purchase(self, context, plan, idempotency_key):  # type: ignore[no-untyped-def]
            self.attempts.append(idempotency_key)
            if len(self.attempts) == 1:
                raise PurchaseOutcomeUnknown("unknown")
            return super().confirm_purchase(context, plan, idempotency_key)

    portal = AmbiguousPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(callback(60, CallbackAction.SELECT_PLAN, "basic"))
    uncertain = handler.handle_callback(callback(61, CallbackAction.CONFIRM_PURCHASE))
    assert "ممکن است پرداخت ثبت شده باشد" in uncertain.messages[0].text
    accepted = handler.handle_callback(callback(62, CallbackAction.CONFIRM_PURCHASE))
    assert "سفارش پذیرفته شد" in accepted.messages[0].text
    assert portal.attempts[0] == portal.attempts[1]


def test_refunded_provider_failure_is_truthful_and_sanitized() -> None:
    portal = InMemoryCustomerPortal()
    plan = portal._purchase_plans[0]
    portal._purchases["failure"] = PurchaseResult(
        "ord_safe1234", "REFUNDED", "FAILED", plan, refunded=True, outcome="FINAL"
    )
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    result = handler.handle_callback(callback(70, CallbackAction.PURCHASE_STATUS, "ord_safe1234"))
    assert "مبلغ سفارش به کیف پول شما بازگردانده شد" in result.messages[0].text
    assert "provider" not in result.messages[0].text.lower()


def test_successful_fake_provider_result_renders_native_service() -> None:
    class SuccessfulPortal(InMemoryCustomerPortal):
        def confirm_purchase(self, context, plan, idempotency_key):  # type: ignore[no-untyped-def]
            return PurchaseResult(
                "ord_safe", "ACTIVE", "SUCCEEDED", plan, service_reference="svc_customer8"
            )

    portal = SuccessfulPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(callback(75, CallbackAction.SELECT_PLAN, "basic"))
    result = handler.handle_callback(callback(76, CallbackAction.CONFIRM_PURCHASE))
    assert "سرویس شما فعال شد" in result.messages[0].text
    assert "svc_customer8" not in result.messages[0].text


def test_provider_write_disabled_stays_provisioning_not_fake_active() -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(callback(77, CallbackAction.SELECT_PLAN, "basic"))
    result = handler.handle_callback(callback(78, CallbackAction.CONFIRM_PURCHASE))
    assert "ساخت سرویس در حال انجام است" in result.messages[0].text
    assert "سرویس شما فعال شد" not in result.messages[0].text


def test_duplicate_telegram_update_does_not_repeat_confirmation() -> None:
    portal = InMemoryCustomerPortal()
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(callback(80, CallbackAction.SELECT_PLAN, "basic"))
    first = handler.handle_callback(callback(81, CallbackAction.CONFIRM_PURCHASE))
    duplicate = handler.handle_callback(callback(81, CallbackAction.CONFIRM_PURCHASE))
    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert len(portal._purchases) == 1


def test_transport_reconciliation_replays_exact_request_and_key() -> None:
    class Client(PrivatePlatformClient):
        calls: list[tuple[object, str | None]] = []

        def _request(
            self, method, path, telegram_id, body=None, idempotency_key=None, content_type=None
        ):  # type: ignore[no-untyped-def]
            _ = method, path, telegram_id, content_type
            self.calls.append((body, idempotency_key))
            if len(self.calls) == 1:
                raise PrivateApiUnavailable("timeout")
            plan = InMemoryCustomerPortal()._purchase_plans[0]
            return {
                "outcome": "ACCEPTED",
                "order_reference": "ord_safe",
                "status": "ACCEPTED",
                "fulfillment_status": "PROVISIONING",
                "plan": {
                    "reference": plan.reference,
                    "title": plan.title,
                    "traffic_gb": plan.traffic_gb,
                    "duration_days": plan.duration_days,
                    "device_limit": plan.device_limit,
                    "location_code": plan.location_code,
                    "location_label": plan.location_label,
                    "quality_code": plan.quality_code,
                    "price_toman": plan.price_toman,
                    "selection": plan.selection,
                },
                "refunded": False,
            }

    client = Client.__new__(Client)
    plan = InMemoryCustomerPortal()._purchase_plans[0]
    result = client.confirm_purchase(
        SimpleContext,
        plan,
        "stable-purchase-key",  # type: ignore[arg-type]
    )
    assert result.order_reference == "ord_safe"
    assert client.calls[0] == client.calls[1]


class SimpleContext:
    telegram_user_id = 42


def test_http_409_is_authoritative_and_never_retried_as_ambiguous(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("x" * 64)
    calls = 0

    def reject(request, timeout):  # type: ignore[no-untyped-def]
        nonlocal calls
        _ = request, timeout
        calls += 1
        raise HTTPError("http://private", 409, "Conflict", {}, BytesIO(b"sensitive-body"))

    monkeypatch.setattr("urllib.request.urlopen", reject)
    client = PrivatePlatformClient("http://api:8000", str(token_file))
    plan = InMemoryCustomerPortal()._purchase_plans[0]
    with pytest.raises(AuthoritativePrivateApiError) as exc:
        client.confirm_purchase(SimpleContext, plan, "stable-key")  # type: ignore[arg-type]
    assert exc.value.status_code == 409
    assert calls == 1
    assert "sensitive-body" not in str(exc.value)


def test_uppercase_active_counts_on_home_and_renders_persian_detail() -> None:
    portal = InMemoryCustomerPortal()
    portal._services[0] = replace(portal._services[0], status="ACTIVE")
    handler = BotCommandHandler(settings(), InMemoryTelegramIdentityService(), portal=portal)
    home = handler.handle_callback(callback(300, CallbackAction.HOME))
    assert "📦 سرویس فعال: ۱" in home.messages[0].text
    detail = handler.handle_callback(callback(301, CallbackAction.OPEN_SERVICE, "svc-a"))
    assert "وضعیت: فعال" in detail.messages[0].text
    assert "ACTIVE" not in detail.messages[0].text
