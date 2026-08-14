from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.internal_api import PrivatePlatformClient
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal, ManualTopup
from telegram_bot.runtime.handlers import (
    BotCommandHandler,
    IncomingCallback,
    IncomingCommand,
    IncomingReceipt,
    IncomingUser,
    callback_policy,
)


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"management-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"management-rate-limit").hexdigest(),
    )


def _user() -> IncomingUser:
    return IncomingUser(42, first_name="علی")


def _callback(
    action: CallbackAction, reference: str = "", update_id: int = 100
) -> IncomingCallback:
    return IncomingCallback(
        update_id,
        f"callback-{update_id}",
        "private",
        _user(),
        BotCallback(action, reference).pack(),
    )


def _request(reference: str, status: str, **amounts: int) -> ManualTopup:
    return ManualTopup(
        reference,
        250_000,
        status,
        datetime(2026, 8, 14, tzinfo=UTC),
        verified_amount_toman=amounts.get("verified"),
        bonus_amount_toman=amounts.get("bonus"),
        total_credited_toman=amounts.get("total"),
    )


class SeedPortal(InMemoryCustomerPortal):
    def seed(self, *requests: ManualTopup) -> None:
        self._manual_topups = {request.reference: request for request in requests}


def test_private_client_cancellation_calls_owned_internal_endpoint(
    tmp_path: Path, monkeypatch: Any
) -> None:
    token = tmp_path / "internal-token"
    token.write_text("x" * 48, encoding="utf-8")
    client = PrivatePlatformClient("http://api:8000", str(token))
    observed: dict[str, object] = {}

    def fake_request(
        method: str,
        path: str,
        telegram_id: int,
        body: object = None,
        idempotency_key: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, object]:
        observed.update(
            method=method,
            path=path,
            telegram_id=telegram_id,
            body=body,
            idempotency_key=idempotency_key,
        )
        return {
            "reference": "mtp_safe",
            "amount_toman": 250_000,
            "status": "CANCELLED",
            "created_at": "2026-08-14T00:00:00+00:00",
        }

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.cancel_manual_topup(
        CustomerContext("opaque", 42, "fa"), "mtp_safe", "stable-cancel-key"
    )
    assert result.status == "CANCELLED"
    assert observed == {
        "method": "POST",
        "path": "/manual-topups/mtp_safe/cancel",
        "telegram_id": 42,
        "body": {},
        "idempotency_key": "stable-cancel-key",
    }


def test_real_cancel_is_mutation_and_local_cancel_does_not_touch_request() -> None:
    portal = SeedPortal()
    context = CustomerContext("user-42", 42, "fa")
    request = portal.create_manual_topup(context, 2_500_000, "create-one")
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)
    assert callback_policy(BotCallback(CallbackAction.CANCEL_MANUAL_TOPUP, request.reference)) == (
        "mutation"
    )
    handler.handle_command(IncomingCommand(1, "private", _user(), "/topup"))
    handler.handle_callback(_callback(CallbackAction.CANCEL_CONVERSATION, update_id=2))
    assert portal.manual_topup(context, request.reference).status == "AWAITING_SUPPORT"  # type: ignore[union-attr]
    cancelled = handler.handle_callback(
        _callback(CallbackAction.CANCEL_MANUAL_TOPUP, request.reference, 3)
    )
    assert "لغو شد" in cancelled.messages[0].text
    assert portal.manual_topup(context, request.reference).status == "CANCELLED"  # type: ignore[union-attr]
    repeated = portal.cancel_manual_topup(
        context, request.reference, f"tg-cancel:{request.reference}"
    )
    assert repeated.status == "CANCELLED"


def test_request_list_renders_every_persian_lifecycle_status() -> None:
    portal = SeedPortal()
    statuses = {
        "AWAITING_SUPPORT": "در انتظار دریافت اطلاعات کارت",
        "AWAITING_RECEIPT": "در انتظار ارسال فیش",
        "UNDER_REVIEW": "در انتظار بررسی",
        "NEEDS_RESUBMISSION": "نیازمند ارسال فیش جدید",
        "APPROVED": "تأییدشده",
        "REJECTED": "ردشده",
        "CANCELLED": "لغوشده",
        "EXPIRED": "منقضی‌شده",
    }
    portal.seed(*(_request(f"mtp_{index:02d}", status) for index, status in enumerate(statuses)))
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)
    result = handler.handle_command(IncomingCommand(10, "private", _user(), "/topups"))
    assert "درخواست‌های کارت‌به‌کارت" in result.messages[0].text
    for label in statuses.values():
        assert label in result.messages[0].text
    callbacks = [
        button.get("callback_data", "") for row in result.messages[0].rows for button in row
    ]
    assert all(len(value.encode()) <= 64 for value in callbacks)
    assert "customer_id" not in result.messages[0].text


def test_detail_breakdown_and_lifecycle_actions_are_safe() -> None:
    portal = SeedPortal()
    approved = _request("mtp_approved", "APPROVED", verified=200_000, bonus=25_000, total=225_000)
    review = _request("mtp_review", "UNDER_REVIEW")
    receipt = _request("mtp_receipt", "AWAITING_RECEIPT")
    portal.seed(approved, review, receipt)
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)

    approved_result = handler.handle_callback(
        _callback(CallbackAction.OPEN_MANUAL_TOPUP, approved.reference, 20)
    )
    text = approved_result.messages[0].text
    assert "مبلغ واریز تأییدشده: 200,000 تومان" in text
    assert "هدیه مدیریت: 25,000 تومان" in text
    assert "مجموع اعتبار افزوده‌شده: 225,000 تومان" in text
    assert all(
        "لغو" not in button["text"] and "فیش" not in button["text"]
        for row in approved_result.messages[0].rows
        for button in row
    )

    review_result = handler.handle_callback(
        _callback(CallbackAction.OPEN_MANUAL_TOPUP, review.reference, 21)
    )
    assert all(
        "لغو" not in button["text"] and "فیش" not in button["text"]
        for row in review_result.messages[0].rows
        for button in row
    )
    receipt_result = handler.handle_callback(
        _callback(CallbackAction.OPEN_MANUAL_TOPUP, receipt.reference, 22)
    )
    labels = [button["text"] for row in receipt_result.messages[0].rows for button in row]
    assert "📎 ارسال فیش" in labels
    assert "❌ لغو درخواست" in labels
    assert not any("شماره کارت" in value for value in (text, *labels))


def test_terminal_detail_clears_only_manual_topup_flow_state() -> None:
    portal = SeedPortal()
    terminal = _request("mtp_terminal", "REJECTED")
    portal.seed(terminal)
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_command(IncomingCommand(30, "private", _user(), "/topup"))
    state = handler.conversations.get("tg:42", datetime.now(UTC))
    handler.conversations.save(
        "tg:42",
        state.__class__(
            current_screen=state.current_screen,
            conversation_kind="manual_topup",
            expected_input="receipt",
            active_manual_topup_reference=terminal.reference,
        ),
    )
    handler.handle_callback(_callback(CallbackAction.OPEN_MANUAL_TOPUP, terminal.reference, 31))
    cleared = handler.conversations.get("tg:42", datetime.now(UTC))
    assert cleared.conversation_kind is None
    assert cleared.expected_input is None
    assert cleared.active_manual_topup_reference is None


def test_receipt_success_status_opens_detail_without_restarting_upload() -> None:
    portal = SeedPortal()
    request = _request("mtp_receipt_status", "AWAITING_RECEIPT")
    portal.seed(request)
    handler = BotCommandHandler(_settings(), InMemoryTelegramIdentityService(), portal=portal)
    handler.handle_callback(_callback(CallbackAction.SEND_RECEIPT, request.reference, 40))
    result = handler.handle_receipt(
        IncomingReceipt(41, "private", _user(), b"safe-image", "image/jpeg")
    )
    status_button = result.messages[0].rows[0][0]
    parsed = BotCallback.parse(status_button["callback_data"])
    assert parsed.action == CallbackAction.OPEN_MANUAL_TOPUP
    detail = handler.handle_callback(
        IncomingCallback(42, "status", "private", _user(), status_button["callback_data"])
    )
    assert "در انتظار بررسی" in detail.messages[0].text
    state = handler.conversations.get("tg:42", datetime.now(UTC))
    assert state.expected_input is None
    assert state.active_manual_topup_reference is None
