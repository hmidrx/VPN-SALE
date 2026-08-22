from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from .application.identity import AccountStatus
from .callbacks import BotCallback, CallbackAction
from .localization import t
from .mini_app import MiniAppRoute, MiniAppUrlBuilder
from .screens import ScreenId


class MenuTarget(StrEnum):
    MINI_APP = "mini_app"
    CALLBACK = "callback"


@dataclass(frozen=True)
class MenuItem:
    item_id: str
    label_key: str
    target: MenuTarget
    order: int
    route: MiniAppRoute | None = None
    action: CallbackAction | None = None
    required_states: frozenset[AccountStatus] = frozenset(
        {AccountStatus.ACTIVE, AccountStatus.PENDING}
    )


@dataclass
class MenuRegistry:
    _items: list[MenuItem] = field(default_factory=list[MenuItem])

    def register(self, item: MenuItem) -> None:
        if any(existing.item_id == item.item_id for existing in self._items):
            raise ValueError("duplicate menu item")
        self._items.append(item)

    def visible(self, status: AccountStatus) -> list[MenuItem]:
        return sorted(
            (item for item in self._items if status in item.required_states),
            key=lambda item: item.order,
        )


def default_menu_registry() -> MenuRegistry:
    registry = MenuRegistry()
    for item_id, label_key, order, action in (
        ("buy", "buy_service", 10, CallbackAction.BUY_SERVICE),
        ("services", "my_services", 20, CallbackAction.MY_SERVICES),
        ("profile", "profile", 30, CallbackAction.PROFILE),
        ("wallet", "wallet", 40, CallbackAction.WALLET),
        ("security", "security", 50, CallbackAction.SECURITY),
        ("support", "support", 60, CallbackAction.SUPPORT),
        ("education", "education", 70, CallbackAction.OPEN_EDUCATION),
        ("status", "status", 80, CallbackAction.STATUS),
        ("privacy", "privacy_button", 100, CallbackAction.PRIVACY),
        ("help", "help_button", 110, CallbackAction.HELP),
        ("refresh", "refresh", 120, CallbackAction.MENU),
        ("home", "open_app", 130, CallbackAction.MENU),
    ):
        registry.register(MenuItem(item_id, label_key, MenuTarget.CALLBACK, order, action=action))
    return registry


def as_button_rows(
    registry: MenuRegistry, status: AccountStatus, locale: str, builder: MiniAppUrlBuilder
) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    for item in registry.visible(status):
        label = t(locale, item.label_key)
        if item.target == MenuTarget.MINI_APP and item.route is not None:
            rows.append([{"text": label, "web_app_url": builder.build(item.route)}])
        elif item.action is not None:
            rows.append([{"text": label, "callback_data": BotCallback(item.action).pack()}])
    return rows


SAFE_RUNTIME_ACTIONS = frozenset(
    {
        "OPEN_STORE",
        "OPEN_SERVICES",
        "OPEN_WALLET",
        "OPEN_WALLET_TOPUP",
        "OPEN_ORDERS",
        "OPEN_PAYMENTS",
        "OPEN_PROFILE",
        "OPEN_SECURITY",
        "OPEN_SUPPORT",
        "OPEN_EDUCATION",
        "SEARCH_GUIDES",
        "SHOW_FAQ",
        "OPEN_STATUS_PAGE",
        "OPEN_MINI_APP",
        "SHOW_HELP",
        "SHOW_CONTACT",
        "GO_HOME",
        "GO_BACK",
    }
)


def runtime_menu_rows(menu: list[dict[str, object]], locale: str) -> list[list[dict[str, str]]]:
    action_map: dict[str, BotCallback] = {
        "OPEN_STORE": BotCallback(CallbackAction.BUY_SERVICE),
        "OPEN_SERVICES": BotCallback(CallbackAction.MY_SERVICES),
        "OPEN_WALLET": BotCallback(CallbackAction.WALLET),
        "OPEN_WALLET_TOPUP": BotCallback(CallbackAction.TOP_UP),
        "OPEN_ORDERS": BotCallback(CallbackAction.OPEN_WEB_APP),
        "OPEN_PAYMENTS": BotCallback(CallbackAction.OPEN_WEB_APP),
        "OPEN_PROFILE": BotCallback(CallbackAction.PROFILE),
        "OPEN_SECURITY": BotCallback(CallbackAction.SECURITY),
        "OPEN_SUPPORT": BotCallback(CallbackAction.SUPPORT),
        "OPEN_EDUCATION": BotCallback(CallbackAction.OPEN_EDUCATION),
        "SEARCH_GUIDES": BotCallback(CallbackAction.SEARCH_GUIDES),
        "SHOW_FAQ": BotCallback(CallbackAction.SHOW_FAQ),
        "OPEN_STATUS_PAGE": BotCallback(CallbackAction.OPEN_STATUS_PAGE),
        "OPEN_MINI_APP": BotCallback(CallbackAction.OPEN_WEB_APP),
        "SHOW_HELP": BotCallback(CallbackAction.HELP),
        "SHOW_CONTACT": BotCallback(CallbackAction.SUPPORT),
        "GO_HOME": BotCallback(CallbackAction.HOME),
        "GO_BACK": BotCallback(CallbackAction.BACK),
    }
    buttons: list[dict[str, str]] = []
    for button in menu[:24]:
        action = str(button.get("action", ""))
        callback = action_map.get(action)
        if action not in SAFE_RUNTIME_ACTIONS or callback is None:
            return []
        label_map = button.get("label")
        label = action
        if isinstance(label_map, dict):
            labels = cast(dict[str, object], label_map)
            localized = labels.get(locale) or labels.get("fa")
            if isinstance(localized, str) and localized.strip():
                label = localized.strip()[:64]
        buttons.append({"text": label, "callback_data": callback.pack()})
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
