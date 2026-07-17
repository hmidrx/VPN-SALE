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
    _items: list[MenuItem] = field(default_factory=list)

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
    registry.register(
        MenuItem("home", "open_app", MenuTarget.MINI_APP, 10, route=MiniAppRoute.HOME)
    )
    registry.register(
        MenuItem("profile", "profile", MenuTarget.MINI_APP, 20, route=MiniAppRoute.PROFILE)
    )
    registry.register(
        MenuItem("security", "security", MenuTarget.MINI_APP, 30, route=MiniAppRoute.SECURITY)
    )
    registry.register(
        MenuItem("wallet", "wallet", MenuTarget.MINI_APP, 35, route=MiniAppRoute.WALLET)
    )
    registry.register(
        MenuItem("help", "help_button", MenuTarget.CALLBACK, 40, action=CallbackAction.HELP)
    )
    registry.register(
        MenuItem(
            "language", "language_button", MenuTarget.CALLBACK, 50, action=CallbackAction.LANGUAGE
        )
    )
    registry.register(
        MenuItem(
            "privacy", "privacy_button", MenuTarget.CALLBACK, 60, action=CallbackAction.PRIVACY
        )
    )
    registry.register(
        MenuItem("refresh", "refresh", MenuTarget.CALLBACK, 70, action=CallbackAction.MENU)
    )
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
