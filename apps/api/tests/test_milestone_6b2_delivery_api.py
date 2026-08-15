from __future__ import annotations

from fastapi.testclient import TestClient

from platform_api.main import app


def test_delivery_admin_endpoints_require_real_admin_authorization() -> None:
    client = TestClient(app)
    matrix = client.get("/api/v1/admin/delivery/compatibility")
    assert matrix.status_code in {401, 403}
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
    assert bad.status_code in {401, 403}


def test_subscription_endpoints_are_no_store_and_never_fabricate_unknown_tokens() -> None:
    client = TestClient(app)
    short = client.get("/subscriptions/short")
    assert short.status_code == 404
    assert short.headers["cache-control"] == "private, no-store"

    unknown = client.get("/subscriptions/" + "a" * 50 + "/sing-box")
    assert unknown.status_code == 404
    assert unknown.headers["cache-control"] == "private, no-store"
