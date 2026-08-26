from __future__ import annotations

from admin_auth_test_support import AdminAuthorizer
from admin_auth_test_support import _admin_authorizer as _admin_authorizer
from fastapi.testclient import TestClient

from platform_api.main import app


def test_knowledge_api_publish_search_recommend_feedback_and_no_draft_leakage(
    admin_authorizer: AdminAuthorizer,
) -> None:
    client = TestClient(app)
    payload = {
        "article_code": "android-safe-guide-api",
        "title": {"fa": "آموزش امن اندروید"},
        "summary": {"fa": "راهنمای تصویری"},
        "slug": "android-safe-guide-api",
        "audience": "AUTHENTICATED_CUSTOMER",
        "operating_systems": ["android"],
        "client_applications": ["approved-app"],
        "delivery_formats": ["manual"],
        "blocks": [
            {"block_type": "HEADING", "order": 1, "text": {"fa": "شروع"}},
            {
                "block_type": "IMAGE",
                "order": 2,
                "text": {"fa": "تصویر"},
                "media_ref": "demo-image",
                "alt_text": {"fa": "نمای برنامه"},
            },
            {"block_type": "WARNING", "order": 3, "text": {"fa": "از منابع ناشناس استفاده نکنید"}},
        ],
    }
    admin_authorizer(None)
    assert client.post("/api/v1/admin/knowledge/drafts", json=payload).status_code == 401
    admin_authorizer({"knowledge.manage", "knowledge.publish"})
    assert client.post("/api/v1/admin/knowledge/drafts", json=payload).status_code == 200
    assert client.get("/api/v1/education/articles/android-safe-guide-api").status_code == 404
    assert (
        client.post("/api/v1/admin/knowledge/articles/android-safe-guide-api/publish").status_code
        == 200
    )
    search = client.get(
        "/api/v1/education/search", params={"q": "اندرويد", "audience": "AUTHENTICATED_CUSTOMER"}
    ).json()
    assert search["query_normalized"] == "اندروید"
    assert search["results"][0]["article_code"] == "android-safe-guide-api"
    rec = client.get(
        "/api/v1/education/recommendations",
        params={
            "audience": "AUTHENTICATED_CUSTOMER",
            "os_code": "android",
            "app_code": "approved-app",
            "delivery_format": "manual",
        },
    ).json()
    assert rec["recommended_article_code"] == "android-safe-guide-api"
    assert (
        client.post(
            "/api/v1/education/articles/android-safe-guide-api/feedback",
            json={"helpful": True, "reason": "مفید بود"},
        ).json()["aggregate_mutated_publication"]
        is False
    )


def test_knowledge_api_rejects_unsafe_blocks_and_status_hides_infrastructure(
    admin_authorizer: AdminAuthorizer,
) -> None:
    client = TestClient(app)
    bad_payload = {
        "article_code": "unsafe-guide-api",
        "title": {"fa": "بد"},
        "summary": {"fa": "بد"},
        "slug": "unsafe-guide-api",
        "audience": "PUBLIC",
        "blocks": [
            {"block_type": "PARAGRAPH", "order": 1, "text": {"fa": "<script>alert(1)</script>"}}
        ],
    }
    admin_authorizer(set())
    assert client.post("/api/v1/admin/knowledge/drafts", json=bad_payload).status_code == 403
    admin_authorizer({"knowledge.manage", "knowledge.publish", "status.manage_incidents"})
    client.post("/api/v1/admin/knowledge/drafts", json=bad_payload)
    assert (
        client.post("/api/v1/admin/knowledge/articles/unsafe-guide-api/publish").status_code == 422
    )
    status = client.get("/api/v1/status/summary")
    assert status.headers["etag"]
    body = status.json()
    assert body["uptime_percentages"] is None
    assert body["vpn_components"] == []
    assert all(component["status"] == "UNKNOWN" for component in body["components"])
    assert (
        client.post(
            "/api/v1/admin/status/incidents",
            json={"title": {"fa": "اختلال"}, "initial_update": "token secret 10.0.0.1"},
        ).status_code
        == 422
    )
