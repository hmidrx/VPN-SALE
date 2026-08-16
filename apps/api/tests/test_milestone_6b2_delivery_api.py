from __future__ import annotations

from fastapi.testclient import TestClient

from platform_api.config import Settings
from platform_api.main import app, create_app
from platform_api.telegram_delivery_internal import router as telegram_delivery_router
from platform_api.telegram_delivery_internal import subscription_urls


TELEGRAM_DELIVERY_PATHS = {
    "/api/v1/internal/telegram/services/{service_reference}/subscription/issue",
    "/api/v1/internal/telegram/services/{service_reference}/subscription/rotate",
    "/api/v1/internal/telegram/services/{service_reference}/subscription/revoke",
    "/api/v1/internal/telegram/services/{service_reference}/connection",
}


def test_delivery_admin_compatibility_and_validation() -> None:
    client = TestClient(app)
    matrix = client.get("/api/v1/admin/delivery/compatibility")
    assert matrix.status_code == 200
    assert "sing_box" in matrix.json()["renderer_contracts"]
    bad = client.post(
        "/api/v1/admin/delivery/profiles/validate",
        json={
            "title": "bad",
            "protocol": "VMESS",
            "transport": "RAW",
            "security": "REALITY",
            "public_address": "https://bad",
            "public_port": 443,
            "remark_template": "safe",
        },
    )
    assert bad.status_code == 200
    assert bad.json()["valid"] is False


def test_subscription_endpoints_are_no_store_and_fail_closed_without_repository_token() -> None:
    client = TestClient(app)
    malformed = client.get("/subscriptions/short")
    assert malformed.status_code == 404
    assert malformed.headers["cache-control"] == "private, no-store"

    syntactically_valid_but_unknown = client.get("/subscriptions/" + "a" * 64 + "/sing-box")
    assert syntactically_valid_but_unknown.status_code == 404
    assert syntactically_valid_but_unknown.headers["cache-control"] == "private, no-store"
    assert syntactically_valid_but_unknown.json()["code"] == "SUBSCRIPTION_NOT_FOUND"


def test_private_telegram_delivery_routes_are_hidden_and_registered() -> None:
    routes = list(telegram_delivery_router.routes)
    assert {getattr(route, "path", "") for route in routes} == TELEGRAM_DELIVERY_PATHS
    assert all(getattr(route, "include_in_schema", None) is False for route in routes)

    application = create_app(Settings(environment="test"))
    app_paths = {getattr(route, "path", "") for route in application.routes}
    assert TELEGRAM_DELIVERY_PATHS <= app_paths


def test_telegram_subscription_urls_are_absolute_and_transient() -> None:
    token = "opaque-" + ("x" * 48)
    urls = subscription_urls(
        Settings(environment="test", subscription_public_origin="https://sub.example.test"),
        token,
    )

    assert set(urls) == {"base64", "links", "mihomo", "clash", "sing_box"}
    assert urls["base64"].endswith("/subscriptions/" + token)
    assert all(
        value.startswith("https://sub.example.test/subscriptions/") for value in urls.values()
    )
    assert all(token in value for value in urls.values())


def test_telegram_subscription_origin_requires_https_and_rejects_credentials() -> None:
    token = "opaque-" + ("y" * 48)
    try:
        subscription_urls(
            Settings(
                environment="production",
                subscription_public_origin="http://sub.example.test",
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
            Settings(environment="test", subscription_public_origin=credential_origin),
            token,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("credential-bearing origin must be rejected")
