from uuid import uuid4

from fastapi.testclient import TestClient

from platform_api.main import app
from platform_api.support import CONVERSATIONS

client = TestClient(app)


def test_customer_support_api_internal_notes_hidden_and_agent_claim_conflict():
    CONVERSATIONS.clear()
    customer_id = str(uuid4())
    agent_id = str(uuid4())
    other_agent_id = str(uuid4())
    created = client.post(
        "/api/v1/customer/support/conversations",
        headers={"Idempotency-Key": "c1", "X-Customer-Id": customer_id},
        json={
            "category_code": "GENERAL",
            "queue_code": "DEFAULT",
            "subject": "سلام",
            "channel": "CUSTOMER_WEB",
        },
    )
    assert created.status_code == 200
    reference = created.json()["reference"]
    version = created.json()["version"]
    claimed = client.post(
        f"/api/v1/admin/support/conversations/{reference}/claim?expected_version={version}",
        headers={
            "X-Admin-Id": agent_id,
            "X-Permissions": "support.read,support.assign,"
            "support.internal_notes.manage,support.internal_notes.read",
        },
    )
    assert claimed.status_code == 200
    conflict = client.post(
        f"/api/v1/admin/support/conversations/{reference}/claim?expected_version={claimed.json()['version']}",
        headers={"X-Admin-Id": other_agent_id, "X-Permissions": "support.read,support.assign"},
    )
    assert conflict.status_code == 409
    note = client.post(
        f"/api/v1/admin/support/conversations/{reference}/messages",
        headers={
            "Idempotency-Key": "n1",
            "X-Admin-Id": agent_id,
            "X-Permissions": "support.read,support.internal_notes.manage,"
            "support.internal_notes.read",
        },
        json={"body": "internal only", "channel": "ADMIN_WEB", "internal": True},
    )
    assert note.status_code == 200
    detail = client.get(
        f"/api/v1/customer/support/conversations/{reference}",
        headers={"X-Customer-Id": customer_id},
    )
    assert detail.status_code == 200
    assert detail.json()["messages"] == []


def test_support_attachment_check_rejects_script():
    bad = client.post(
        "/api/v1/customer/support/attachments/check",
        json={
            "filename": "x.js",
            "content_type": "application/javascript",
            "content_hex_prefix": "616c657274",
            "byte_size": 5,
        },
    )
    assert bad.status_code == 403
    png = client.post(
        "/api/v1/customer/support/attachments/check",
        json={
            "filename": "x.png",
            "content_type": "image/png",
            "content_hex_prefix": "89504e470d0a1a0a",
            "byte_size": 8,
        },
    )
    assert png.status_code == 200
    assert png.json()["state"] == "READY"
