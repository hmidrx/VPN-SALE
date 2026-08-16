from __future__ import annotations

from hashlib import sha256

from telegram_bot.application.identity import InMemoryTelegramIdentityService
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.config import BotMode, BotSettings
from telegram_bot.internal_api import PrivateApiUnavailable
from telegram_bot.portal import CustomerContext, InMemoryCustomerPortal
from telegram_bot.runtime.account_security import AccountSecurityBotCommandHandler
from telegram_bot.runtime.handlers import IncomingCallback, IncomingCommand, IncomingUser


def _settings() -> BotSettings:
    return BotSettings(
        enabled=True,
        token=sha256(b"account-security-token").hexdigest(),
        mode=BotMode.POLLING,
        environment="TEST",
        mini_app_base_url="https://app.example.test",
        mini_app_allowed_hosts=("app.example.test",),
        rate_limit_secret=sha256(b"account-security-rate-limit").hexdigest(),
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


def _handler(portal: InMemoryCustomerPortal | None = None) -> AccountSecurityBotCommandHandler:
    return AccountSecurityBotCommandHandler(
        _settings(), InMemoryTelegramIdentityService(), portal=portal or InMemoryCustomerPortal()
    )


def _actions(result: object) -> set[CallbackAction]:
    values: set[CallbackAction] = set()
    messages = getattr(result, "messages")
    for row in messages[0].rows:
        for button in row:
            data = button.get("callback_data")
            if data:
                values.add(BotCallback.parse(data).action)
    return values


def test_profile_exposes_native_account_security_entry() -> None:
    result = _handler().handle_callback(_callback(CallbackAction.PROFILE, update_id=10))

    assert CallbackAction.SECURITY in _actions(result)
    assert "نسخه وب" not in result.messages[0].text


def test_security_command_lists_sessions_without_sensitive_identifiers() -> None:
    result = _handler().handle_command(
        IncomingCommand(11, "private", _user(), "/security")
    )

    assert "امنیت حساب" in result.messages[0].text
    assert "Customer web" in result.messages[0].text
    assert "sess-web" not in result.messages[0].text
    assert CallbackAction.REVOKE_SESSION in _actions(result)


def test_revoke_requires_second_confirmation_and_does_not_revoke_current_session() -> None:
    portal = InMemoryCustomerPortal()
    handler = _handler(portal)

    first = handler.handle_callback(
        _callback(CallbackAction.REVOKE_SESSION, "sess-web", update_id=20)
    )
    assert CallbackAction.CONFIRM_REVOKE in _actions(first)
    assert any(item.ref == "sess-web" for item in portal.sessions(CustomerContext("x", 42, "fa")))

    confirmed = handler.handle_callback(
        _callback(CallbackAction.CONFIRM_REVOKE, "sess-web", update_id=21)
    )
    assert "موفقیت" in confirmed.messages[0].text
    assert not any(item.ref == "sess-web" for item in portal.sessions(CustomerContext("x", 42, "fa")))

    current = handler.handle_callback(
        _callback(CallbackAction.REVOKE_SESSION, "sess-current", update_id=22)
    )
    assert CallbackAction.CONFIRM_REVOKE not in _actions(current)
    assert any(
        item.ref == "sess-current" for item in portal.sessions(CustomerContext("x", 42, "fa"))
    )


class _AmbiguousRevokePortal(InMemoryCustomerPortal):
    def revoke_session(self, context: CustomerContext, session_ref: str) -> bool:
        super().revoke_session(context, session_ref)
        raise PrivateApiUnavailable("ambiguous")


def test_ambiguous_revoke_reconciles_with_safe_read_instead_of_repeating_mutation() -> None:
    portal = _AmbiguousRevokePortal()
    result = _handler(portal).handle_callback(
        _callback(CallbackAction.CONFIRM_REVOKE, "sess-web", update_id=30)
    )

    assert "موفقیت" in result.messages[0].text
    assert not any(item.ref == "sess-web" for item in portal.sessions(CustomerContext("x", 42, "fa")))
