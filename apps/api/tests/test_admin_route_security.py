from __future__ import annotations

import inspect

import pytest
from admin_auth_test_support import AdminAuthorizer
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from platform_api.customer_auth.routes import current_customer_session_dependency
from platform_api.main import app
from platform_api.management import current_admin

pytest_plugins = ("admin_auth_test_support",)

SECURED_ADMIN_MODULES = {
    "platform_api.delivery",
    "platform_api.knowledge_status",
    "platform_api.resellers",
    "platform_api.usage",
}


def _dependency_calls(dependant: Dependant) -> set[object]:
    calls: set[object] = set()
    for child in dependant.dependencies:
        if child.call is not None:
            calls.add(child.call)
        calls.update(_dependency_calls(child))
    return calls


def _permission_codes(route: APIRoute) -> set[str]:
    result: set[str] = set()
    for dependant in route.dependant.dependencies:
        call = dependant.call
        if not inspect.isfunction(call) or call.__name__ != "dep":
            continue
        result.update(
            value
            for value in inspect.getclosurevars(call).nonlocals.values()
            if isinstance(value, str)
        )
    return result


def _route(path: str, method: str) -> APIRoute:
    return next(
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and method in route.methods
    )


def test_target_admin_routes_have_an_admin_authentication_dependency() -> None:
    target_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/v1/admin/")
        and route.endpoint.__module__ in SECURED_ADMIN_MODULES
    ]
    assert target_routes
    unguarded = [
        f"{','.join(sorted(route.methods))} {route.path}"
        for route in target_routes
        if current_admin not in _dependency_calls(route.dependant)
    ]
    assert unguarded == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/admin/management/resellers"),
        ("POST", "/api/v1/admin/knowledge/media/inspect?content_type=image/png"),
        ("GET", "/api/v1/admin/service-usage/dashboard"),
        ("GET", "/api/v1/admin/delivery/compatibility"),
    ],
)
def test_target_admin_surfaces_fail_closed_for_anonymous_requests(
    method: str,
    path: str,
    admin_authorizer: AdminAuthorizer,
) -> None:
    admin_authorizer(None)
    assert TestClient(app).request(method, path).status_code == 401


def test_target_admin_surfaces_enforce_permission_and_allow_authorized_admin(
    admin_authorizer: AdminAuthorizer,
) -> None:
    client = TestClient(app)
    admin_authorizer(set())
    admin_authorizer(
        {
            "resellers.read",
            "service_usage.read",
            "delivery_compatibility.read",
        }
    )
    assert client.get("/api/v1/admin/management/resellers").status_code == 200
    assert client.get("/api/v1/admin/service-usage/dashboard").status_code == 200
    assert client.get("/api/v1/admin/delivery/compatibility").status_code == 200


def test_fleet_mutations_require_write_permissions() -> None:
    expected = {
        ("/api/v1/admin/fleet/resources", "POST"): "providers.manage",
        (
            "/api/v1/admin/fleet/health/observations",
            "POST",
        ): "fleet.manage_health_policies",
        (
            "/api/v1/admin/fleet/capacity/snapshots",
            "POST",
        ): "fleet.manage_capacity_policies",
    }
    for (path, method), permission in expected.items():
        assert permission in _permission_codes(_route(path, method))


def test_service_operation_actor_identity_is_not_caller_supplied(
    admin_authorizer: AdminAuthorizer,
) -> None:
    customer_routes = [
        _route("/api/v1/customer/service-operations/{service_reference}/eligibility", "GET"),
        _route("/api/v1/customer/service-operations", "POST"),
        _route("/api/v1/reseller/service-operations/{service_reference}/eligibility", "GET"),
    ]
    for route in customer_routes:
        assert current_customer_session_dependency in _dependency_calls(route.dependant)
        assert not {parameter.name for parameter in route.dependant.query_params}.intersection(
            {"x_customer_id", "x_reseller_id"}
        )

    approve = _route("/api/v1/admin/service-operations/{operation_id}/approve", "POST")
    assert current_admin in _dependency_calls(approve.dependant)
    assert "x_admin_actor" not in {parameter.name for parameter in approve.dependant.query_params}

    admin_authorizer(None)
    client = TestClient(app)
    assert (
        client.get("/api/v1/customer/service-operations/service-test/eligibility").status_code
        == 401
    )
    assert (
        client.get("/api/v1/reseller/service-operations/service-test/eligibility").status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/admin/service-operations/00000000-0000-4000-8000-000000000001/approve"
        ).status_code
        == 401
    )
