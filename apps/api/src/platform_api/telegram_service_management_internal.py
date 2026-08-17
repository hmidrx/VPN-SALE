# pyright: reportPrivateUsage=false
"""Private Telegram-native service management projections and quotes."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from vpnsale_domain.service_operations import (
    ServiceOperation,
    ServiceOperationActorType,
    ServiceOperationAttachmentSuccessPolicy,
    ServiceOperationCommercialOrigin,
    ServiceOperationDesiredChange,
    ServiceOperationDomainError,
    ServiceOperationPolicyVersion,
    ServiceOperationPriceRule,
    ServiceOperationType,
)

from .service_models import ServiceModel, ServiceOperationModel, ServiceOperationPolicyVersionModel
from .telegram_internal import Database, InternalAuth, _customer_id, _no_store

router = APIRouter(
    prefix="/api/v1/internal/telegram/service-management",
    tags=["internal-telegram-service-management"],
    include_in_schema=False,
)

_BILLABLE = {
    ServiceOperationType.RENEW,
    ServiceOperationType.ADD_TRAFFIC,
    ServiceOperationType.EXTEND_EXPIRY,
    ServiceOperationType.CHANGE_DEVICE_LIMIT,
}
CUSTOMER_NATIVE_OPERATION_TYPES = (
    ServiceOperationType.RENEW,
    ServiceOperationType.ADD_TRAFFIC,
)
_ELIGIBLE_LIFECYCLES = {"ACTIVE", "EXPIRED", "SUSPENDED", "DEGRADED"}
_GIB = 1024**3
_MAX_RENEW_DAYS = 3650
_MAX_ADD_TRAFFIC_GIB = 10 * 1024


class OperationQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_type: ServiceOperationType
    amount: int = Field(gt=0)


def _service(db: Database, customer_id: str, reference: str) -> ServiceModel:
    row = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service_not_found")
    return row


def _operation_set(snapshot: dict[str, object], key: str) -> frozenset[ServiceOperationType]:
    raw = snapshot.get(key)
    if not isinstance(raw, list):
        return frozenset()
    values: set[ServiceOperationType] = set()
    for value in cast(list[object], raw):
        if not isinstance(value, str):
            raise ValueError(f"invalid {key}")
        values.add(ServiceOperationType(value))
    return frozenset(values)


def _string_set(snapshot: dict[str, object], key: str) -> frozenset[str]:
    raw = snapshot.get(key)
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ValueError(f"invalid {key}")
    values: set[str] = set()
    for value in cast(list[object], raw):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"invalid {key}")
        values.add(value)
    return frozenset(values)


def _required_permissions(
    snapshot: dict[str, object],
) -> dict[ServiceOperationType, str]:
    raw = snapshot.get("required_permissions")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("invalid required_permissions")
    permissions: dict[ServiceOperationType, str] = {}
    for operation, permission in cast(dict[object, object], raw).items():
        if (
            not isinstance(operation, str)
            or not isinstance(permission, str)
            or not permission.strip()
        ):
            raise ValueError("invalid required_permissions")
        permissions[ServiceOperationType(operation)] = permission
    return permissions


def _optional_positive_int(snapshot: dict[str, object], key: str) -> int | None:
    value = snapshot.get(key)
    if value is None:
        return None
    if type(value) is not int or cast(int, value) <= 0:
        raise ValueError(f"invalid {key}")
    return cast(int, value)


def _optional_cooldown(snapshot: dict[str, object]) -> timedelta | None:
    value = snapshot.get("cooldown_seconds")
    if value is None:
        value = snapshot.get("cooldown")
    if value is None:
        return None
    if type(value) is not int or cast(int, value) < 0:
        raise ValueError("invalid cooldown")
    return timedelta(seconds=cast(int, value))


def _policy_domain(row: ServiceOperationPolicyVersionModel) -> ServiceOperationPolicyVersion:
    snapshot = row.immutable_snapshot
    if not isinstance(snapshot, dict):
        raise ValueError("invalid policy snapshot")
    rule_raw = snapshot.get("price_rule", "NONE")
    if not isinstance(rule_raw, str):
        raise ValueError("invalid price_rule")
    fixed_price = snapshot.get("fixed_price_rial", 0)
    unit_price = snapshot.get("unit_price_rial", 0)
    if type(fixed_price) is not int or type(unit_price) is not int:
        raise ValueError("invalid price")
    success_raw = snapshot.get("attachment_success_policy", "ALL_REQUIRED")
    if not isinstance(success_raw, str):
        raise ValueError("invalid attachment policy")
    published_at = row.published_at
    if published_at is None:
        raise ValueError("unpublished policy")
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return ServiceOperationPolicyVersion(
        policy_id=UUID(row.policy_id),
        version_id=UUID(row.id),
        version_number=row.version_number,
        status=row.status,
        allowed_operation_types=_operation_set(snapshot, "allowed_operation_types"),
        customer_self_service=_operation_set(snapshot, "customer_self_service"),
        reseller_service=_operation_set(snapshot, "reseller_service"),
        admin_only=_operation_set(snapshot, "admin_only"),
        billable_operations=_operation_set(snapshot, "billable_operations"),
        high_risk_operations=_operation_set(snapshot, "high_risk_operations"),
        required_permissions=_required_permissions(snapshot),
        price_rule=ServiceOperationPriceRule(rule_raw),
        fixed_price_rial=cast(int, fixed_price),
        unit_price_rial=cast(int, unit_price),
        min_amount=_optional_positive_int(snapshot, "min_amount"),
        max_amount=_optional_positive_int(snapshot, "max_amount"),
        increment=_optional_positive_int(snapshot, "increment"),
        cooldown=_optional_cooldown(snapshot),
        maximum_operation_count=_optional_positive_int(snapshot, "maximum_operation_count"),
        attachment_success_policy=ServiceOperationAttachmentSuccessPolicy(success_raw),
        at_least_n=_optional_positive_int(snapshot, "at_least_n"),
        required_provider_capabilities=_string_set(snapshot, "required_provider_capabilities"),
        published_at=published_at,
    )


def _price_rule_compatible(
    operation_type: ServiceOperationType, policy: ServiceOperationPolicyVersion
) -> bool:
    if policy.price_rule is ServiceOperationPriceRule.FIXED_RIAL:
        return policy.fixed_price_rial > 0
    if operation_type is ServiceOperationType.RENEW:
        return (
            policy.price_rule is ServiceOperationPriceRule.PER_DAY_RIAL
            and policy.unit_price_rial > 0
        )
    if operation_type is ServiceOperationType.ADD_TRAFFIC:
        return (
            policy.price_rule is ServiceOperationPriceRule.PER_GIB_RIAL
            and policy.unit_price_rial > 0
        )
    return False


def _published_customer_policy(
    db: Database, operation_type: ServiceOperationType
) -> tuple[ServiceOperationPolicyVersionModel, ServiceOperationPolicyVersion]:
    rows = list(
        db.scalars(
            select(ServiceOperationPolicyVersionModel)
            .where(
                ServiceOperationPolicyVersionModel.status == "PUBLISHED",
                ServiceOperationPolicyVersionModel.published_at.is_not(None),
            )
            .order_by(ServiceOperationPolicyVersionModel.published_at.desc())
        )
    )
    for row in rows:
        try:
            policy = _policy_domain(row)
        except (ValueError, ServiceOperationDomainError):
            continue
        if (
            operation_type in policy.allowed_operation_types
            and operation_type in policy.customer_self_service
            and operation_type in policy.billable_operations
            and _price_rule_compatible(operation_type, policy)
        ):
            return row, policy
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="service_operation_policy_unavailable",
    )


def _quote_options(
    operation_type: ServiceOperationType, policy: ServiceOperationPolicyVersion
) -> dict[str, object] | None:
    if operation_type is ServiceOperationType.RENEW:
        hard_max = _MAX_RENEW_DAYS
        unit = "DAY"
        candidates = (1, 7, 15, 30, 60, 90, 180, 365)
    elif operation_type is ServiceOperationType.ADD_TRAFFIC:
        hard_max = _MAX_ADD_TRAFFIC_GIB
        unit = "GIB"
        candidates = (1, 5, 10, 20, 50, 100, 200, 500)
    else:
        return None
    minimum = max(policy.min_amount or 1, 1)
    maximum = min(policy.max_amount or hard_max, hard_max)
    increment = policy.increment or 1
    if minimum > maximum:
        return None
    suggestions = [
        amount for amount in candidates if minimum <= amount <= maximum and amount % increment == 0
    ]
    if not suggestions:
        first = ((minimum + increment - 1) // increment) * increment
        if first > maximum:
            return None
        suggestions = [first]
    return {
        "unit": unit,
        "minimum_amount": minimum,
        "maximum_amount": maximum,
        "increment": increment,
        "suggested_amounts": suggestions[:8],
    }


def _desired_change(operation_type: ServiceOperationType, amount: int) -> dict[str, object]:
    if operation_type is ServiceOperationType.RENEW:
        if amount > _MAX_RENEW_DAYS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="renew_amount_too_large"
            )
        return {
            "traffic_delta_bytes": 0,
            "duration_delta_seconds": amount * 24 * 60 * 60,
            "renew_days": amount,
        }
    if operation_type is ServiceOperationType.ADD_TRAFFIC:
        if amount > _MAX_ADD_TRAFFIC_GIB:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="traffic_amount_too_large"
            )
        return {
            "traffic_delta_bytes": amount * _GIB,
            "duration_delta_seconds": 0,
            "traffic_gib": amount,
        }
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operation_not_supported")


def _digest_idempotency(customer_id: str, service_id: str, key: str) -> str:
    return "sha256:" + hashlib.sha256(f"{customer_id}:{service_id}:{key}".encode()).hexdigest()


def _quote_view(operation: ServiceOperationModel) -> dict[str, object]:
    quote = operation.quote_snapshot or {}
    return {
        "operation_reference": operation.id,
        "service_id": operation.service_id,
        "operation_type": operation.operation_type,
        "status": operation.status,
        "amount": operation.desired_change.get("renew_days")
        or operation.desired_change.get("traffic_gib"),
        "price_rial": quote.get("price_rial"),
        "currency": "IRR",
        "expires_at": quote.get("expires_at"),
        "policy_version_id": operation.policy_version_id,
    }


@router.get("/{service_reference}/eligibility")
def service_management_eligibility(
    service_reference: str,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
) -> dict[str, object]:
    customer_id = _customer_id(db, x_telegram_subject)
    service = _service(db, customer_id, service_reference)
    lifecycle_eligible = service.lifecycle in _ELIGIBLE_LIFECYCLES
    operations: list[dict[str, object]] = []
    for operation_type in CUSTOMER_NATIVE_OPERATION_TYPES:
        reason_codes: list[str] = []
        options: dict[str, object] | None = None
        if not lifecycle_eligible:
            reason_codes.append("SERVICE_NOT_ELIGIBLE")
        else:
            try:
                _, policy = _published_customer_policy(db, operation_type)
            except HTTPException:
                reason_codes.append("POLICY_UNAVAILABLE")
            else:
                options = _quote_options(operation_type, policy)
                if options is None:
                    reason_codes.append("POLICY_UNAVAILABLE")
        operations.append(
            {
                "operation_type": operation_type.value,
                "eligible": not reason_codes,
                "billable": operation_type in _BILLABLE,
                "requires_authoritative_quote": operation_type in _BILLABLE,
                "safe_reason_codes": reason_codes,
                "quote_options": options,
            }
        )
    _no_store(response)
    return {
        "service_reference": service.public_reference,
        "lifecycle": service.lifecycle,
        "operations": operations,
    }


@router.post("/{service_reference}/quotes")
def create_service_operation_quote(
    service_reference: str,
    body: OperationQuoteRequest,
    response: Response,
    _: InternalAuth,
    db: Database,
    x_telegram_subject: Annotated[int, Header(gt=0)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=200)],
) -> dict[str, object]:
    if body.operation_type not in CUSTOMER_NATIVE_OPERATION_TYPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="operation_not_supported")
    customer_id = _customer_id(db, x_telegram_subject)
    service = _service(db, customer_id, service_reference)
    if service.lifecycle not in _ELIGIBLE_LIFECYCLES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="service_not_eligible")
    desired_change = _desired_change(body.operation_type, body.amount)
    digest = _digest_idempotency(customer_id, service.id, idempotency_key)
    existing = db.scalar(
        select(ServiceOperationModel).where(
            ServiceOperationModel.service_id == service.id,
            ServiceOperationModel.idempotency_key_digest == digest,
        )
    )
    if existing is not None:
        if (
            existing.operation_type != body.operation_type.value
            or existing.desired_change != desired_change
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="idempotency_conflict")
        _no_store(response)
        return _quote_view(existing)

    policy_row, policy = _published_customer_policy(db, body.operation_type)
    now = datetime.now(UTC)
    try:
        domain_operation = ServiceOperation.create(
            service_id=UUID(service.id),
            operation_type=body.operation_type,
            requester_type=ServiceOperationActorType.CUSTOMER,
            requester_id=customer_id,
            policy_version=policy,
            desired_change=ServiceOperationDesiredChange(
                traffic_delta_bytes=cast(int, desired_change.get("traffic_delta_bytes", 0)),
                duration_delta_seconds=cast(int, desired_change.get("duration_delta_seconds", 0)),
            ),
            idempotency_key_digest=digest,
            reason_code="TELEGRAM_SELF_SERVICE",
            now=now,
            amount=body.amount,
            commercial_origin=ServiceOperationCommercialOrigin.CUSTOMER_CHECKOUT,
        )
    except ServiceOperationDomainError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.code.value) from exc
    if domain_operation.quote is None or domain_operation.quote.price_rial <= 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="authoritative_quote_unavailable")
    quote = domain_operation.quote
    quote_snapshot: dict[str, object] = {
        "quote_id": str(quote.quote_id),
        "price_rial": quote.price_rial,
        "currency": "IRR",
        "expires_at": quote.expires_at.isoformat(),
        "price_snapshot": quote.price_snapshot,
        "commercial_origin": quote.commercial_origin.value,
        "service_version": service.version,
        "issued_at": now.isoformat(),
    }
    operation = ServiceOperationModel(
        id=str(domain_operation.operation_id),
        service_id=service.id,
        operation_type=body.operation_type.value,
        status=domain_operation.status.value,
        requester_type=ServiceOperationActorType.CUSTOMER.value,
        requester_id=customer_id,
        idempotency_key_digest=digest,
        reason_code="TELEGRAM_SELF_SERVICE",
        policy_version_id=policy_row.id,
        policy_snapshot=policy_row.immutable_snapshot,
        desired_change=desired_change,
        quote_snapshot=quote_snapshot,
        created_at=now,
        updated_at=now,
    )
    db.add(operation)
    db.flush()
    _no_store(response)
    return _quote_view(operation)
