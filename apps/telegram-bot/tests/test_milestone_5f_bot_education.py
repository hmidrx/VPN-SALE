from telegram_bot.application.identity import AccountStatus
from telegram_bot.callbacks import BotCallback, CallbackAction
from telegram_bot.menu import SAFE_RUNTIME_ACTIONS, as_button_rows, default_menu_registry
from telegram_bot.mini_app import MiniAppRoute, MiniAppUrlBuilder


def test_education_and_status_safe_actions_and_menu_links_contain_no_tokens() -> None:
    assert {
        "OPEN_EDUCATION",
        "SEARCH_GUIDES",
        "SHOW_FAQ",
        "OPEN_STATUS_PAGE",
    } <= SAFE_RUNTIME_ACTIONS
    packed = BotCallback(CallbackAction.OPEN_STATUS_PAGE).pack()
    assert BotCallback.parse(packed).action is CallbackAction.OPEN_STATUS_PAGE
    builder = MiniAppUrlBuilder("https://example.test", ("example.test",), production_like=True)
    rows = as_button_rows(default_menu_registry(), AccountStatus.ACTIVE, "fa", builder)
    callbacks = [
        button["callback_data"] for row in rows for button in row if "callback_data" in button
    ]
    assert BotCallback(CallbackAction.OPEN_EDUCATION).pack() in callbacks
    assert BotCallback(CallbackAction.STATUS).pack() in callbacks
    assert all("token" not in data and "initData" not in data for data in callbacks)
    assert MiniAppRoute.EDUCATION in MiniAppRoute
