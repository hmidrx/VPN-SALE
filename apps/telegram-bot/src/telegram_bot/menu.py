from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from .application.identity import AccountStatus
from .callbacks import BotCallback, CallbackAction
from .localization import t
from .mini_app import MiniAppRoute, MiniAppUrlBuilder


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
        ("language", "language_button", 90, CallbackAction.LANGUAGE),
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
    rows: list[list[dict[str, str]]] = []
    for button in menu[:32]:
        action = str(button.get("action", ""))
        if action not in SAFE_RUNTIME_ACTIONS:
            return []
        label_map = button.get("label")
        label = action
        if isinstance(label_map, dict):
            labels = cast(dict[str, object], label_map)
            localized = labels.get(locale) or labels.get("fa") or labels.get("en")
            if isinstance(localized, str) and localized.strip():
                label = localized[:64]
        rows.append([{"text": label, "callback_data": f"cfg:{action}"}])
    return rows
