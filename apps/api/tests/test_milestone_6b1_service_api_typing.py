from __future__ import annotations

import pytest
from fastapi import HTTPException

from platform_api.services import snapshot_non_negative_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2, 2),
        ("3", 3),
        (None, 0),
    ],
)
def test_snapshot_non_negative_int_accepts_valid_snapshot_values(
    value: object, expected: int
) -> None:
    assert snapshot_non_negative_int(value, "required_attachment_count", 0) == expected


@pytest.mark.parametrize(
    "value",
    [
        "two",
        True,
        False,
        1.5,
        [1],
        {"count": 1},
        -1,
    ],
)
def test_snapshot_non_negative_int_rejects_invalid_snapshot_values(value: object) -> None:
    with pytest.raises(HTTPException) as exc_info:
        snapshot_non_negative_int(value, "required_attachment_count", 0)
    assert exc_info.value.detail == {
        "code": "SERVICE_ENTITLEMENT_INVALID",
        "field": "required_attachment_count",
    }


def test_api_and_customer_service_modules_import() -> None:
    from platform_api.main import app
    from platform_api.services import customer_service_detail, customer_services

    assert app
    assert customer_services
    assert customer_service_detail


def test_customer_session_dependency_has_authoritative_model_return_type() -> None:
    from typing import get_type_hints

    from platform_api.customer_auth.routes import current_customer_session_dependency
    from platform_api.identity.models import CustomerSessionModel

    hints = get_type_hints(current_customer_session_dependency)
    assert hints["return"] is CustomerSessionModel


def test_customer_service_routes_only_accept_authenticated_session_authority() -> None:
    import inspect

    from platform_api.services import customer_service_detail, customer_services

    for route in (customer_services, customer_service_detail):
        parameters = inspect.signature(route).parameters
        assert "customer_session" in parameters
        assert "x_customer_id" not in parameters


def test_customer_services_list_filters_with_authenticated_session_user_id() -> None:
    from unittest.mock import MagicMock

    from platform_api.identity.models import CustomerSessionModel
    from platform_api.services import customer_services

    session = CustomerSessionModel(user_id="customer-from-session")
    db = MagicMock()
    db.scalars.return_value = []

    assert customer_services(customer_session=session, db=db) == []
    statement = db.scalars.call_args.args[0]
    assert "customer-from-session" in statement.compile().params.values()


def test_customer_service_detail_uses_session_and_hides_unowned_reference() -> None:
    from unittest.mock import MagicMock

    from platform_api.identity.models import CustomerSessionModel
    from platform_api.services import customer_service_detail

    session = CustomerSessionModel(user_id="owning-customer")
    db = MagicMock()
    db.scalar.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        customer_service_detail(
            service_reference="service-public-reference",
            customer_session=session,
            db=db,
        )

    assert exc_info.value.status_code == 404
    statement = db.scalar.call_args.args[0]
    values = statement.compile().params.values()
    assert "owning-customer" in values
    assert "service-public-reference" in values
