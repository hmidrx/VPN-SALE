from inspect import getsource

from fastapi.testclient import TestClient

from platform_api import main
from platform_api.main import app

client = TestClient(app)


def test_legacy_in_memory_support_routes_are_not_mounted() -> None:
    assert client.get("/api/v1/customer/support/conversations").status_code == 404
    assert client.get("/api/v1/admin/support/inbox").status_code == 404
    assert client.post("/api/v1/reseller/support/conversations", json={}).status_code == 404


def test_production_app_does_not_import_legacy_support_module() -> None:
    source = getsource(main)
    assert "from .support import" not in source
    assert "customer_support_router" not in source
    assert "reseller_support_router" not in source
    assert "admin_support_router" not in source
