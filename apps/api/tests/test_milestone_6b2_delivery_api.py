from __future__ import annotations

from fastapi.testclient import TestClient

from platform_api.main import app


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


def test_subscription_endpoints_are_no_store_and_uniform() -> None:
    client = TestClient(app)
    missing = client.get("/subscriptions/short")
    assert missing.status_code == 404
    assert missing.headers["cache-control"] == "private, no-store"
    ok = client.get("/subscriptions/" + "a" * 50 + "/sing-box")
    assert ok.status_code == 200
    assert ok.headers["cache-control"] == "private, no-store"
