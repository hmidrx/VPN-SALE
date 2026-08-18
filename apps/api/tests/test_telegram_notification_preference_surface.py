from __future__ import annotations

from fastapi.routing import APIRoute

from platform_api import telegram_internal
from platform_api.config import Settings
from platform_api.main import create_app

_PUBLIC_TELEGRAM_PREFERENCE_PREFIX = "/api/v1/customer/notification-preferences/telegram/"
_PRIVATE_PREFERENCE_PATH = "/api/v1/internal/telegram/notification-preferences"
_PRIVATE_PREFERENCE_PATCH_PATH = (
    "/api/v1/internal/telegram/notification-preferences/{preference_key}"
)


def test_raw_telegram_id_notification_preference_routes_are_not_public() -> None:
    schema = create_app(Settings()).openapi()

    assert not any(path.startswith(_PUBLIC_TELEGRAM_PREFERENCE_PREFIX) for path in schema["paths"])


def test_private_telegram_notification_preference_routes_remain_registered() -> None:
    methods_by_path = {
        route.path: route.methods
        for route in telegram_internal.router.routes
        if isinstance(route, APIRoute)
    }

    assert "GET" in methods_by_path[_PRIVATE_PREFERENCE_PATH]
    assert "PATCH" in methods_by_path[_PRIVATE_PREFERENCE_PATCH_PATH]
