from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4

from vpnsale_domain.provider_mutations import ProviderOperationStatus
from vpnsale_domain.services import ServiceLifecycle


class ServiceOperationErrorCode(StrEnum):
    OPERATION_NOT_ELIGIBLE = "OPERATION_NOT_ELIGIBLE"
    OPERATION_POLICY_INVALID = "OPERATION_POLICY_INVALID"
    OPERATION_POLICY_UNPUBLISHED = "OPERATION_POLICY_UNPUBLISHED"
    OPERATION_STATUS_INVALID = "OPERATION_STATUS_INVALID"
    OPERATION_PAYMENT_REQUIRED = "OPERATION_PAYMENT_REQUIRED"
    OPERATION_APPROVAL_REQUIRED = "OPERATION_APPROVAL_REQUIRED"
    OPERATION_SELF_APPROVAL_DENIED = "OPERATION_SELF_APPROVAL_DENIED"
    OPERATION_CONCURRENT_MODIFICATION = "OPERATION_CONCURRENT_MODIFICATION"
    OPERATION_IDEMPOTENCY_CONFLICT = "OPERATION_IDEMPOTENCY_CONFLICT"
    OPERATION_PRICE_MANIPULATION = "OPERATION_PRICE_MANIPULATION"
    OPERATION_REDUCTION_BELOW_USAGE = "OPERATION_REDUCTION_BELOW_USAGE"
    OPERATION_EXPIRY_IN_PAST = "OPERATION_EXPIRY_IN_PAST"
    OPERATION_PROVIDER_CAPABILITY_MISSING = "OPERATION_PROVIDER_CAPABILITY_MISSING"
    OPERATION_PROVIDER_RECERTIFICATION_REQUIRED = "OPERATION_PROVIDER_RECERTIFICATION_REQUIRED"
    OPERATION_PARTIAL_APPLICATION = "OPERATION_PARTIAL_APPLICATION"
    OPERATION_UNCERTAIN = "OPERATION_UNCERTAIN"
    OPERATION_SECRET_LEAKAGE = "OPERATION_SECRET_LEAKAGE"  # noqa: S105


@dataclass(frozen=True)
class ServiceOperationDomainError(ValueError):
    code: ServiceOperationErrorCode
    safe_message: str


class ServiceOperationType(StrEnum):
    RENEW = "RENEW"
    ADD_TRAFFIC = "ADD_TRAFFIC"
    REDUCE_TRAFFIC = "REDUCE_TRAFFIC"
    EXTEND_EXPIRY = "EXTEND_EXPIRY"
    REDUCE_EXPIRY = "REDUCE_EXPIRY"
    CHANGE_DEVICE_LIMIT = "CHANGE_DEVICE_LIMIT"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    RESET_TRAFFIC = "RESET_TRAFFIC"
    CLEAR_CLIENT_IPS = "CLEAR_CLIENT_IPS"
    CLEAR_HWID = "CLEAR_HWID"
    ROTATE_CREDENTIAL = "ROTATE_CREDENTIAL"
    REVOKE_SUBSCRIPTION = "REVOKE_SUBSCRIPTION"
    ROTATE_SUBSCRIPTION_TOKEN = "ROTATE_SUBSCRIPTION_TOKEN"  # noqa: S105
    REFRESH_DELIVERY_PROFILE = "REFRESH_DELIVERY_PROFILE"


class ServiceOperationStatus(StrEnum):
    DRAFT = "DRAFT"
    CHECKING_ELIGIBILITY = "CHECKING_ELIGIBILITY"
    QUOTED = "QUOTED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    RECONCILING = "RECONCILING"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ServiceOperationActorType(StrEnum):
    CUSTOMER = "CUSTOMER"
    RESELLER = "RESELLER"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"


class ServiceOperationCommercialOrigin(StrEnum):
    NONE = "NONE"
    CUSTOMER_CHECKOUT = "CUSTOMER_CHECKOUT"
    RESELLER_FUNDED_CHECKOUT = "RESELLER_FUNDED_CHECKOUT"
    ADMIN_ORDER = "ADMIN_ORDER"


class ServiceOperationAttachmentSuccessPolicy(StrEnum):
    ALL_REQUIRED = "ALL_REQUIRED"
    AT_LEAST_N = "AT_LEAST_N"
    BEST_EFFORT_OPTIONAL = "BEST_EFFORT_OPTIONAL"


class ServiceOperationPriceRule(StrEnum):
    NONE = "NONE"
    FIXED_RIAL = "FIXED_RIAL"
    PER_GIB_RIAL = "PER_GIB_RIAL"
    PER_DAY_RIAL = "PER_DAY_RIAL"
    PER_DEVICE_RIAL = "PER_DEVICE_RIAL"


class ServiceOperationApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ServiceOperationReconciliationOutcome(StrEnum):
    MATCHED = "MATCHED"
    REMOTE_DIFFERENT = "REMOTE_DIFFERENT"
    PARTIALLY_APPLIED = "PARTIALLY_APPLIED"
    OPERATION_UNCERTAIN = "OPERATION_UNCERTAIN"
    PROVIDER_RECERTIFICATION_REQUIRED = "PROVIDER_RECERTIFICATION_REQUIRED"
    FORWARD_REPAIR_AVAILABLE = "FORWARD_REPAIR_AVAILABLE"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


BILLABLE_DEFAULTS = {
    ServiceOperationType.RENEW,
    ServiceOperationType.ADD_TRAFFIC,
    ServiceOperationType.EXTEND_EXPIRY,
    ServiceOperationType.CHANGE_DEVICE_LIMIT,
}
DESTRUCTIVE_TYPES = {ServiceOperationType.REDUCE_TRAFFIC, ServiceOperationType.REDUCE_EXPIRY}
DELIVERY_REFRESH_TYPES = {
    ServiceOperationType.ROTATE_CREDENTIAL,
    ServiceOperationType.REVOKE_SUBSCRIPTION,
    ServiceOperationType.ROTATE_SUBSCRIPTION_TOKEN,
    ServiceOperationType.REFRESH_DELIVERY_PROFILE,
    ServiceOperationType.SUSPEND,
    ServiceOperationType.RESUME,
}


@dataclass(frozen=True)
class ServiceOperationPolicyVersion:
    policy_id: UUID
    version_id: UUID
    version_number: int
    status: str
    allowed_operation_types: frozenset[ServiceOperationType]
    customer_self_service: frozenset[ServiceOperationType]
    reseller_service: frozenset[ServiceOperationType]
    admin_only: frozenset[ServiceOperationType]
    billable_operations: frozenset[ServiceOperationType]
    high_risk_operations: frozenset[ServiceOperationType]
    required_permissions: dict[ServiceOperationType, str]
    price_rule: ServiceOperationPriceRule = ServiceOperationPriceRule.NONE
    fixed_price_rial: int = 0
    unit_price_rial: int = 0
    min_amount: int | None = None
    max_amount: int | None = None
    increment: int | None = None
    cooldown: timedelta | None = None
    maximum_operation_count: int | None = None
    attachment_success_policy: ServiceOperationAttachmentSuccessPolicy = (
        ServiceOperationAttachmentSuccessPolicy.ALL_REQUIRED
    )
    at_least_n: int | None = None
    required_provider_capabilities: frozenset[str] = frozenset()
    published_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.fixed_price_rial < 0 or self.unit_price_rial < 0:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_POLICY_INVALID, "money must be integer rial"
            )
        if self.increment is not None and self.increment <= 0:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_POLICY_INVALID, "increment must be positive"
            )

    def assert_published(self) -> None:
        if self.status != "PUBLISHED" or self.published_at is None:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_POLICY_UNPUBLISHED, "policy is not published"
            )

    def assert_actor_allowed(
        self, operation_type: ServiceOperationType, actor_type: ServiceOperationActorType
    ) -> None:
        self.assert_published()
        if operation_type not in self.allowed_operation_types:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "operation disabled"
            )
        if (
            actor_type is ServiceOperationActorType.CUSTOMER
            and operation_type not in self.customer_self_service
        ):
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "customer not allowed"
            )
        if (
            actor_type is ServiceOperationActorType.RESELLER
            and operation_type not in self.reseller_service
        ):
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "reseller not allowed"
            )

    def authoritative_price_rial(
        self, operation_type: ServiceOperationType, amount: int | None
    ) -> int:
        if operation_type not in self.billable_operations:
            return 0
        qty = amount or 1
        if self.min_amount is not None and qty < self.min_amount:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "below minimum"
            )
        if self.max_amount is not None and qty > self.max_amount:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "above maximum"
            )
        if self.increment is not None and qty % self.increment != 0:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "bad increment"
            )
        if self.price_rule is ServiceOperationPriceRule.FIXED_RIAL:
            return self.fixed_price_rial
        if self.price_rule in {
            ServiceOperationPriceRule.PER_GIB_RIAL,
            ServiceOperationPriceRule.PER_DAY_RIAL,
            ServiceOperationPriceRule.PER_DEVICE_RIAL,
        }:
            return qty * self.unit_price_rial
        return self.fixed_price_rial


@dataclass(frozen=True)
class ServiceUsageSnapshot:
    observed_at: datetime
    lifetime_used_bytes: int
    provider_counter_bytes: int
    stale_after: datetime
    source: str

    def assert_fresh(self, now: datetime) -> None:
        if self.observed_at.tzinfo is None or self.stale_after.tzinfo is None or now.tzinfo is None:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "naive usage time"
            )
        if now > self.stale_after:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "usage snapshot stale"
            )


@dataclass(frozen=True)
class ServiceOperationDesiredChange:
    traffic_delta_bytes: int = 0
    duration_delta_seconds: int = 0
    new_expiry: datetime | None = None
    device_limit: int | None = None
    ip_limit: int | None = None
    hwid_limit: int | None = None
    enabled: bool | None = None
    reset_generation: int | None = None
    delivery_refresh_required: bool = False

    def sanitized_digest(self) -> str:
        raw = "|".join(
            [
                str(self.traffic_delta_bytes),
                str(self.duration_delta_seconds),
                self.new_expiry.isoformat() if self.new_expiry else "",
                str(self.device_limit),
                str(self.ip_limit),
                str(self.hwid_limit),
                str(self.enabled),
                str(self.reset_generation),
                str(self.delivery_refresh_required),
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class ServiceOperationQuote:
    quote_id: UUID
    price_rial: int
    expires_at: datetime
    price_snapshot: dict[str, object]
    commercial_origin: ServiceOperationCommercialOrigin

    def assert_active(self, now: datetime) -> None:
        if self.expires_at <= now:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_PAYMENT_REQUIRED, "quote expired"
            )


@dataclass(frozen=True)
class ServiceOperationApproval:
    approval_id: UUID
    requested_by: str
    decided_by: str
    decision: ServiceOperationApprovalDecision
    reason_code: str
    decided_at: datetime

    def assert_valid(self) -> None:
        if self.requested_by == self.decided_by:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_SELF_APPROVAL_DENIED, "self approval denied"
            )


@dataclass(frozen=True)
class ServiceOperationAttachmentPlan:
    attachment_id: UUID
    required: bool
    provider_operation_id: UUID | None
    capability: str
    expected_snapshot_digest: str
    status: ProviderOperationStatus = ProviderOperationStatus.PLANNED
    verified: bool = False
    uncertain: bool = False


@dataclass(frozen=True)
class ServiceStateRevision:
    revision_id: UUID
    service_id: UUID
    revision_number: int
    operation_id: UUID
    traffic_limit_bytes: int | None
    expires_at: datetime | None
    device_limit: int | None
    service_lifecycle: ServiceLifecycle
    created_at: datetime
    previous_revision_id: UUID | None = None


@dataclass(frozen=True)
class ServiceOperation:
    operation_id: UUID
    service_id: UUID
    operation_type: ServiceOperationType
    status: ServiceOperationStatus
    requester_type: ServiceOperationActorType
    requester_id: str
    policy_version: ServiceOperationPolicyVersion
    desired_change: ServiceOperationDesiredChange
    idempotency_key_digest: str
    reason_code: str
    version: int = 1
    quote: ServiceOperationQuote | None = None
    order_id: UUID | None = None
    invoice_id: UUID | None = None
    payment_id: UUID | None = None
    approvals: tuple[ServiceOperationApproval, ...] = ()
    attachment_plans: tuple[ServiceOperationAttachmentPlan, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def create(
        cls,
        *,
        service_id: UUID,
        operation_type: ServiceOperationType,
        requester_type: ServiceOperationActorType,
        requester_id: str,
        policy_version: ServiceOperationPolicyVersion,
        desired_change: ServiceOperationDesiredChange,
        idempotency_key_digest: str,
        reason_code: str,
        now: datetime,
        amount: int | None = None,
        commercial_origin: ServiceOperationCommercialOrigin = ServiceOperationCommercialOrigin.NONE,
    ) -> ServiceOperation:
        policy_version.assert_actor_allowed(operation_type, requester_type)
        price = policy_version.authoritative_price_rial(operation_type, amount)
        status = (
            ServiceOperationStatus.AWAITING_PAYMENT
            if price > 0
            else ServiceOperationStatus.PENDING_APPROVAL
            if operation_type in policy_version.high_risk_operations
            else ServiceOperationStatus.QUEUED
        )
        quote = None
        if price > 0:
            quote = ServiceOperationQuote(
                uuid4(),
                price,
                now + timedelta(minutes=15),
                {
                    "policy_version_id": str(policy_version.version_id),
                    "operation_type": operation_type.value,
                    "amount": amount or 1,
                    "price_rial": price,
                },
                commercial_origin,
            )
        return cls(
            uuid4(),
            service_id,
            operation_type,
            status,
            requester_type,
            requester_id,
            policy_version,
            desired_change,
            idempotency_key_digest,
            reason_code,
            quote=quote,
            created_at=now,
        )

    def mark_paid(
        self, *, order_id: UUID, invoice_id: UUID, payment_id: UUID, now: datetime
    ) -> ServiceOperation:
        if self.status is not ServiceOperationStatus.AWAITING_PAYMENT or self.quote is None:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_STATUS_INVALID, "not awaiting payment"
            )
        self.quote.assert_active(now)
        next_status = (
            ServiceOperationStatus.PENDING_APPROVAL
            if self.operation_type in self.policy_version.high_risk_operations
            else ServiceOperationStatus.QUEUED
        )
        return replace(
            self,
            status=next_status,
            order_id=order_id,
            invoice_id=invoice_id,
            payment_id=payment_id,
            version=self.version + 1,
        )

    def approve(self, approver_id: str, reason_code: str, now: datetime) -> ServiceOperation:
        if self.status is not ServiceOperationStatus.PENDING_APPROVAL:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_STATUS_INVALID, "approval not pending"
            )
        approval = ServiceOperationApproval(
            uuid4(),
            self.requester_id,
            approver_id,
            ServiceOperationApprovalDecision.APPROVED,
            reason_code,
            now,
        )
        approval.assert_valid()
        return replace(
            self,
            status=ServiceOperationStatus.QUEUED,
            approvals=self.approvals + (approval,),
            version=self.version + 1,
        )

    def begin_execution(self) -> ServiceOperation:
        if self.status not in {
            ServiceOperationStatus.QUEUED,
            ServiceOperationStatus.APPROVED,
            ServiceOperationStatus.PAID,
        }:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_STATUS_INVALID, "not executable"
            )
        return replace(self, status=ServiceOperationStatus.EXECUTING, version=self.version + 1)

    def finish_verification(
        self, plans: tuple[ServiceOperationAttachmentPlan, ...]
    ) -> ServiceOperation:
        required = [p for p in plans if p.required]
        verified_required = [p for p in required if p.verified and not p.uncertain]
        if len(verified_required) == len(required):
            status = ServiceOperationStatus.SUCCEEDED
        elif any(p.uncertain for p in required):
            status = ServiceOperationStatus.UNCERTAIN
        elif verified_required:
            status = ServiceOperationStatus.PARTIALLY_APPLIED
        else:
            status = ServiceOperationStatus.FAILED
        return replace(self, status=status, attachment_plans=plans, version=self.version + 1)


def validate_desired_reduction(
    *,
    operation_type: ServiceOperationType,
    current_traffic_limit_bytes: int | None,
    desired_traffic_limit_bytes: int | None,
    current_expiry: datetime | None,
    desired_expiry: datetime | None,
    usage: ServiceUsageSnapshot | None,
    now: datetime,
) -> None:
    if operation_type is ServiceOperationType.REDUCE_TRAFFIC:
        if current_traffic_limit_bytes is None or desired_traffic_limit_bytes is None:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE,
                "unlimited reduction requires explicit finite target",
            )
        if desired_traffic_limit_bytes < 0:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_REDUCTION_BELOW_USAGE, "negative allowance"
            )
        if usage is None:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_NOT_ELIGIBLE, "usage required"
            )
        usage.assert_fresh(now)
        if desired_traffic_limit_bytes < usage.lifetime_used_bytes:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_REDUCTION_BELOW_USAGE, "below consumed traffic"
            )
    if operation_type is ServiceOperationType.REDUCE_EXPIRY:
        if current_expiry is None or desired_expiry is None or desired_expiry <= now:
            raise ServiceOperationDomainError(
                ServiceOperationErrorCode.OPERATION_EXPIRY_IN_PAST, "expiry must remain future"
            )
