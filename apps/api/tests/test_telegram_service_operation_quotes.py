# pyright: reportPrivateUsage=false
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from vpnsale_domain.service_operations import (
    ServiceOperationAttachmentSuccessPolicy,
    ServiceOperationPriceRule,
    ServiceOperationType,
)

from platform_api.service_models import ServiceOperationPolicyVersionModel
from platform_api.telegram_service_management_internal import (
    OperationQuoteRequest,
    _policy_domain,
    _price_rule_compatible,
    _quote_options,
)


def _policy_row(
    *,
    price_rule: str = "PER_GIB_RIAL",
    fixed_price_rial: int = 0,
    unit_price_rial: int = 10_000,
) -> ServiceOperationPolicyVersionModel:
    policy_id = str(uuid4())
    version_id = str(uuid4())
    now = datetime(2026, 8, 17, tzinfo=UTC)
    return ServiceOperationPolicyVersionModel(
        id=version_id,
        policy_id=policy_id,
        version_number=7,
        status="PUBLISHED",
        immutable_snapshot={
            "allowed_operation_types": ["ADD_TRAFFIC"],
            "customer_self_service": ["ADD_TRAFFIC"],
            "reseller_service": [],
            "admin_only": ["REDUCE_TRAFFIC"],
            "billable_operations": ["ADD_TRAFFIC"],
            "high_risk_operations": ["REDUCE_TRAFFIC"],
            "required_permissions": {"REDUCE_TRAFFIC": "services.reduce_entitlement"},
            "price_rule": price_rule,
            "fixed_price_rial": fixed_price_rial,
            "unit_price_rial": unit_price_rial,
            "min_amount": 1,
            "max_amount": 100,
            "increment": 5,
            "cooldown_seconds": 120,
            "maximum_operation_count": 3,
            "attachment_success_policy": "AT_LEAST_N",
            "at_least_n": 1,
            "required_provider_capabilities": ["UPDATE_CLIENT", "READ_CLIENT"],
        },
        published_at=now,
        created_at=now,
    )


def test_quote_request_forbids_client_supplied_price() -> None:
    with pytest.raises(ValidationError):
        OperationQuoteRequest.model_validate(
            {
                "operation_type": "ADD_TRAFFIC",
                "amount": 10,
                "price_rial": 1,
            }
        )


def test_policy_snapshot_conversion_preserves_execution_guards() -> None:
    policy = _policy_domain(_policy_row())

    assert policy.version_number == 7
    assert policy.required_permissions == {
        ServiceOperationType.REDUCE_TRAFFIC: "services.reduce_entitlement"
    }
    assert policy.cooldown == timedelta(seconds=120)
    assert policy.maximum_operation_count == 3
    assert policy.attachment_success_policy is ServiceOperationAttachmentSuccessPolicy.AT_LEAST_N
    assert policy.at_least_n == 1
    assert policy.required_provider_capabilities == frozenset({"UPDATE_CLIENT", "READ_CLIENT"})


def test_unit_price_rule_must_match_native_operation() -> None:
    traffic_policy = _policy_domain(_policy_row(price_rule="PER_GIB_RIAL"))
    assert _price_rule_compatible(ServiceOperationType.ADD_TRAFFIC, traffic_policy)
    assert not _price_rule_compatible(ServiceOperationType.RENEW, traffic_policy)

    fixed_policy = _policy_domain(
        _policy_row(
            price_rule="FIXED_RIAL",
            fixed_price_rial=50_000,
            unit_price_rial=0,
        )
    )
    assert _price_rule_compatible(ServiceOperationType.ADD_TRAFFIC, fixed_policy)
    assert _price_rule_compatible(ServiceOperationType.RENEW, fixed_policy)
    assert fixed_policy.price_rule is ServiceOperationPriceRule.FIXED_RIAL


def test_quote_options_only_expose_policy_valid_amounts() -> None:
    policy = _policy_domain(_policy_row())

    assert _quote_options(ServiceOperationType.ADD_TRAFFIC, policy) == {
        "unit": "GIB",
        "minimum_amount": 1,
        "maximum_amount": 100,
        "increment": 5,
        "suggested_amounts": [5, 10, 20, 50, 100],
    }
