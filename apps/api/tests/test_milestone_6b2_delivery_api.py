from __future__ import annotations

from fastapi.testclient import TestClient

from platform_api.main import app


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


def test_private_telegram_delivery_routes_are_registered_and_hidden_from_openapi() -> None:
    app_paths = {getattr(route, "path", "") for route in app.routes}
    assert TELEGRAM_DELIVERY_PATHS <= app_paths

    openapi_paths = set(app.openapi()["paths"])
    assert TELEGRAM_DELIVERY_PATHS.isdisjoint(openapi_paths)
