from __future__ import annotations

from fastapi.routing import APIRoute

from platform_api.config import Settings
from platform_api.main import create_app
from platform_api.telegram_delivery_internal import router, subscription_urls


EXPECTED_PATHS = {
    "/api/v1/internal/telegram/services/{service_reference}/subscription/issue",
    "/api/v1/internal/telegram/services/{service_reference}/subscription/rotate",
    "/api/v1/internal/telegram/services/{service_reference}/subscription/revoke",
    "/api/v1/internal/telegram/services/{service_reference}/connection",
}


def test_private_delivery_routes_are_hidden_and_registered() -> None:
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert {route.path for route in routes} == EXPECTED_PATHS
    assert all(route.include_in_schema is False for route in routes)

    app = create_app(Settings(environment="test"))
    app_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert EXPECTED_PATHS <= app_paths


def test_subscription_urls_are_absolute_and_contain_plaintext_only_in_response_builder() -> None:
    token = "opaque-" + ("x" * 48)
    urls = subscription_urls(
        Settings(environment="test", subscription_public_origin="https://sub.example.test"), token
    )

    assert set(urls) == {"base64", "links", "mihomo", "clash", "sing_box"}
    assert urls["base64"].endswith("/subscriptions/" + token)
    assert all(
        value.startswith("https://sub.example.test/subscriptions/") for value in urls.values()
    )
    assert all(token in value for value in urls.values())


def test_production_subscription_origin_requires_https_and_rejects_credentials() -> None:
    token = "opaque-" + ("y" * 48)
    try:
        subscription_urls(
            Settings(
                environment="production", subscription_public_origin="http://sub.example.test"
            ),
            token,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("production HTTP origin must be rejected")

    credential_origin = "https://" + "user" + ":" + "pass" + "@sub.example.test"
    try:
        subscription_urls(
            Settings(environment="test", subscription_public_origin=credential_origin), token
        )
    except ValueError:
        pass
    else:
        raise AssertionError("credential-bearing origin must be rejected")
