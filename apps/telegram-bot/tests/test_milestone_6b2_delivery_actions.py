from __future__ import annotations

import pytest

from telegram_bot.callbacks import BotCallback, CallbackAction


def test_delivery_safe_actions_are_opaque_and_bounded() -> None:
    for action in (
        CallbackAction.MY_SERVICES,
        CallbackAction.OPEN_SERVICE,
        CallbackAction.OPEN_CONFIGS,
        CallbackAction.OPEN_SUBSCRIPTION,
        CallbackAction.ROTATE_SUBSCRIPTION,
        CallbackAction.REVOKE_SUBSCRIPTION,
        CallbackAction.CONFIRM_REVOKE_SUBSCRIPTION,
        CallbackAction.OPEN_SERVICE_GUIDE,
    ):
        data = BotCallback(action, "opaque-ref").pack()
        assert len(data.encode()) <= 64
        assert BotCallback.parse(data).action is action
        assert "11111111-1111" not in data
        assert "vless://" not in data
    with pytest.raises(ValueError):
        BotCallback(CallbackAction.OPEN_CONFIGS, "x" * 80).pack()
