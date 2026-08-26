from __future__ import annotations

from fastapi.routing import APIRoute

from platform_api.main import app


def test_online_gateway_routes_are_not_mounted() -> None:
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert not any(path.startswith("/api/payment-webhooks") for path in paths)
    assert not any(path.startswith("/api/v1/customer/payments") for path in paths)
    assert not any(path.startswith("/api/v1/admin/payments") for path in paths)


def test_card_to_card_and_wallet_purchase_surfaces_remain_mounted() -> None:
    methods = {
        (route.path, method)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }

    assert ("/api/v1/customer/manual-topups", "POST") in methods
    assert ("/api/v1/admin/manual-topups/{reference}/approve", "POST") in methods
    assert ("/api/v1/customer/checkout", "POST") in methods
