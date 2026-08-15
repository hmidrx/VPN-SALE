from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4

from vpnsale_domain.orders import OrderFinancialStatus, OrderStatus
from vpnsale_domain.provider_mutations import ProviderOperationStatus, ProviderWriteMode


class ServiceErrorCode(StrEnum):
    FULFILLMENT_NOT_ELIGIBLE = "FULFILLMENT_NOT_ELIGIBLE"
    FULFILLMENT_ALREADY_EXISTS = "FULFILLMENT_ALREADY_EXISTS"
    FULFILLMENT_BLOCKED_BY_REFUND = "FULFILLMENT_BLOCKED_BY_REFUND"
    SERVICE_ALREADY_EXISTS = "SERVICE_ALREADY_EXISTS"
    SERVICE_NOT_FOUND = "SERVICE_NOT_FOUND"
    SERVICE_STATE_INVALID = "SERVICE_STATE_INVALID"
    SERVICE_ENTITLEMENT_INVALID = "SERVICE_ENTITLEMENT_INVALID"
    ALLOCATION_POLICY_NOT_FOUND = "ALLOCATION_POLICY_NOT_FOUND"
    ALLOCATION_POLICY_UNPUBLISHED = "ALLOCATION_POLICY_UNPUBLISHED"
    ALLOCATION_POLICY_INVALID = "ALLOCATION_POLICY_INVALID"
    ALLOCATION_NO_ELIGIBLE_TARGET = "ALLOCATION_NO_ELIGIBLE_TARGET"
    ALLOCATION_CAPACITY_EXHAUSTED = "ALLOCATION_CAPACITY_EXHAUSTED"
    ALLOCATION_INVENTORY_STALE = "ALLOCATION_INVENTORY_STALE"
    ALLOCATION_RESERVATION_CONFLICT = "ALLOCATION_RESERVATION_CONFLICT"
    ALLOCATION_TARGET_UNAVAILABLE = "ALLOCATION_TARGET_UNAVAILABLE"
    PROVISIONING_ALREADY_RUNNING = "PROVISIONING_ALREADY_RUNNING"
    PROVISIONING_PROVIDER_WRITE_DISABLED = "PROVISIONING_PROVIDER_WRITE_DISABLED"
    PROVISIONING_PARTIAL_FAILURE = "PROVISIONING_PARTIAL_FAILURE"
    PROVISIONING_UNCERTAIN = "PROVISIONING_UNCERTAIN"
    PROVISIONING_POSTCONDITION_FAILED = "PROVISIONING_POSTCONDITION_FAILED"
    SERVICE_RECONCILIATION_REQUIRED = "SERVICE_RECONCILIATION_REQUIRED"
    SERVICE_COMPENSATION_REQUIRED = "SERVICE_COMPENSATION_REQUIRED"
    SERVICE_MANUAL_REVIEW_REQUIRED = "SERVICE_MANUAL_REVIEW_REQUIRED"
    PROVIDER_REQUIRES_RECERTIFICATION = "PROVIDER_REQUIRES_RECERTIFICATION"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class ServiceDomainError(ValueError):
    code: ServiceErrorCode
    safe_message: str


class ServiceLifecycle(StrEnum):
    PENDING_ALLOCATION = "PENDING_ALLOCATION"
    ALLOCATED = "ALLOCATED"
    PROVISIONING = "PROVISIONING"
    VERIFYING = "VERIFYING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    PROVISIONING_FAILED = "PROVISIONING_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    EXPIRED = "EXPIRED"


class AttachmentStatus(StrEnum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    OPERATION_QUEUED = "OPERATION_QUEUED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


class AllocationPolicyStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"
    ARCHIVED = "ARCHIVED"


class AllocationStrategy(StrEnum):
    SINGLE_TARGET = "SINGLE_TARGET"
    ALL_REQUIRED_TARGETS = "ALL_REQUIRED_TARGETS"
    AT_LEAST_N_TARGETS = "AT_LEAST_N_TARGETS"
    ONE_PER_GROUP = "ONE_PER_GROUP"


class TargetRole(StrEnum):
    PRIMARY = "PRIMARY"
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    SECONDARY = "SECONDARY"


class IdentityStrategy(StrEnum):
    SHARED = "SHARED"
    PER_ATTACHMENT = "PER_ATTACHMENT"


class ReconciliationOutcome(StrEnum):
    MATCHED = "MATCHED"
    REMOTE_MISSING = "REMOTE_MISSING"
    REMOTE_EXTRA = "REMOTE_EXTRA"
    REMOTE_DIFFERENT = "REMOTE_DIFFERENT"
    PARTIALLY_PROVISIONED = "PARTIALLY_PROVISIONED"
    DUPLICATE_REMOTE_IDENTITY = "DUPLICATE_REMOTE_IDENTITY"
    STALE_INVENTORY = "STALE_INVENTORY"
    PROVIDER_UNCERTAIN = "PROVIDER_UNCERTAIN"
    RECERTIFICATION_REQUIRED = "RECERTIFICATION_REQUIRED"
    REPAIR_PLAN_REQUIRED = "REPAIR_PLAN_REQUIRED"
    COMPENSATION_REQUIRED = "COMPENSATION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


@dataclass(frozen=True)
class CommercialOrderState:
    order_id: UUID
    order_item_id: UUID
    order_status: OrderStatus
    financial_status: OrderFinancialStatus
    payment_status: str
    refund_status: str | None = None

    def assert_eligible(self) -> None:
        if self.refund_status in {"REQUESTED", "COMPLETED", "CHARGEBACK"}:
            raise ServiceDomainError(
                ServiceErrorCode.FULFILLMENT_BLOCKED_BY_REFUND, "refund blocks provisioning"
            )
        if (
            self.order_status is not OrderStatus.READY_FOR_FULFILLMENT
            or self.financial_status is not OrderFinancialStatus.PAID
            or self.payment_status != "CAPTURED"
        ):
            raise ServiceDomainError(
                ServiceErrorCode.FULFILLMENT_NOT_ELIGIBLE, "order is not eligible"
            )


@dataclass(frozen=True)
class ServiceEntitlement:
    product_id: UUID
    product_version_id: UUID
    plan_reference: str
    product_label: str
    traffic_limit_bytes: int | None
    duration_seconds: int | None
    starts_at: datetime
    expires_at: datetime | None
    device_limit: int | None
    quantity_unit_index: int
    required_attachment_count: int
    optional_attachment_count: int
    payer_type: str
    payer_reference: str
    beneficiary_customer_id: UUID
    reseller_id: UUID | None
    order_id: UUID
    invoice_id: UUID
    payment_id: UUID
    safe_remark: str
    protocol_eligibility: tuple[str, ...] = ()
    transport_eligibility: tuple[str, ...] = ()
    location_eligibility: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.starts_at.tzinfo is None:
            raise ServiceDomainError(ServiceErrorCode.SERVICE_ENTITLEMENT_INVALID, "start is naive")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ServiceDomainError(
                ServiceErrorCode.SERVICE_ENTITLEMENT_INVALID, "expiry is naive"
            )
        if self.traffic_limit_bytes is not None and self.traffic_limit_bytes < 0:
            raise ServiceDomainError(ServiceErrorCode.SERVICE_ENTITLEMENT_INVALID, "bad traffic")
        if self.required_attachment_count < 1:
            raise ServiceDomainError(
                ServiceErrorCode.SERVICE_ENTITLEMENT_INVALID, "missing attachment"
            )
        if any(ch in self.safe_remark for ch in "\r\n\t") or "://" in self.safe_remark:
            raise ServiceDomainError(ServiceErrorCode.SERVICE_ENTITLEMENT_INVALID, "unsafe remark")


@dataclass(frozen=True)
class AllocationTarget:
    target_id: UUID
    panel_id: UUID
    node_id: UUID | None
    inbound_id: str
    provider_kind: str
    provider_version: str
    contract_digest: str
    role: TargetRole
    priority: int
    weight: int
    max_capacity: int
    safety_reserve: int
    active_allocations: int
    pending_reservations: int
    inventory_observed_at: datetime
    inventory_max_age: timedelta
    healthy: bool
    maintenance: bool
    write_mode: ProviderWriteMode
    supports_shared_identity: bool
    tags: frozenset[str] = frozenset()

    def available_capacity(self, now: datetime) -> int:
        if self.inventory_observed_at.tzinfo is None or now.tzinfo is None:
            raise ServiceDomainError(ServiceErrorCode.ALLOCATION_POLICY_INVALID, "naive time")
        if now - self.inventory_observed_at > self.inventory_max_age:
            raise ServiceDomainError(ServiceErrorCode.ALLOCATION_INVENTORY_STALE, "inventory stale")
        used = self.active_allocations + self.pending_reservations + self.safety_reserve
        return max(self.max_capacity - used, 0)

    def assert_candidate(self, now: datetime) -> None:
        if self.maintenance or not self.healthy:
            raise ServiceDomainError(
                ServiceErrorCode.ALLOCATION_TARGET_UNAVAILABLE, "target unavailable"
            )
        if self.write_mode is not ProviderWriteMode.WRITE_ENABLED:
            raise ServiceDomainError(
                ServiceErrorCode.PROVISIONING_PROVIDER_WRITE_DISABLED, "provider writes disabled"
            )
        if self.available_capacity(now) <= 0:
            raise ServiceDomainError(
                ServiceErrorCode.ALLOCATION_CAPACITY_EXHAUSTED, "capacity exhausted"
            )


@dataclass(frozen=True)
class AllocationPolicyVersion:
    policy_id: UUID
    version_id: UUID
    version_number: int
    status: AllocationPolicyStatus
    strategy: AllocationStrategy
    success_policy: str
    identity_strategy: IdentityStrategy
    required_target_count: int
    required_tags: frozenset[str] = frozenset()
    published_at: datetime | None = None

    def publish(self, now: datetime) -> AllocationPolicyVersion:
        if self.status is not AllocationPolicyStatus.VALIDATED:
            raise ServiceDomainError(ServiceErrorCode.ALLOCATION_POLICY_INVALID, "not validated")
        return replace(self, status=AllocationPolicyStatus.PUBLISHED, published_at=now)

    def assert_published(self) -> None:
        if self.status is not AllocationPolicyStatus.PUBLISHED:
            raise ServiceDomainError(
                ServiceErrorCode.ALLOCATION_POLICY_UNPUBLISHED, "policy is not published"
            )


@dataclass(frozen=True)
class AllocationDecision:
    decision_id: UUID
    policy_version: AllocationPolicyVersion
    selected_targets: tuple[AllocationTarget, ...]
    rejected_reason_codes: tuple[str, ...]
    decision_key: str


def select_targets(
    policy: AllocationPolicyVersion,
    candidates: tuple[AllocationTarget, ...],
    service_key: str,
    now: datetime,
) -> AllocationDecision:
    policy.assert_published()
    valid: list[AllocationTarget] = []
    rejected: list[str] = []
    for target in candidates:
        try:
            target.assert_candidate(now)
            if not policy.required_tags.issubset(target.tags):
                raise ServiceDomainError(
                    ServiceErrorCode.ALLOCATION_TARGET_UNAVAILABLE, "missing required tags"
                )
            if (
                policy.identity_strategy is IdentityStrategy.SHARED
                and not target.supports_shared_identity
            ):
                raise ServiceDomainError(
                    ServiceErrorCode.ALLOCATION_POLICY_INVALID, "shared identity unsupported"
                )
            valid.append(target)
        except ServiceDomainError as exc:
            rejected.append(exc.code.value)
    if not valid:
        raise ServiceDomainError(
            ServiceErrorCode.ALLOCATION_NO_ELIGIBLE_TARGET, "no eligible allocation target"
        )
    ordered = sorted(
        valid,
        key=lambda item: (item.priority, _stable_weight(service_key, item), item.target_id.hex),
    )
    count = (
        1 if policy.strategy is AllocationStrategy.SINGLE_TARGET else policy.required_target_count
    )
    selected = tuple(ordered[:count])
    if len(selected) < count:
        raise ServiceDomainError(
            ServiceErrorCode.ALLOCATION_NO_ELIGIBLE_TARGET, "not enough eligible targets"
        )
    return AllocationDecision(uuid4(), policy, selected, tuple(rejected), service_key)


def _stable_weight(service_key: str, target: AllocationTarget) -> int:
    digest = hashlib.sha256(
        f"{service_key}:{target.target_id}:{target.weight}".encode()
    ).hexdigest()
    return int(digest[:12], 16) // max(target.weight, 1)


@dataclass(frozen=True)
class AllocationReservation:
    reservation_id: UUID
    service_id: UUID
    target_id: UUID
    status: str
    reserved_at: datetime
    expires_at: datetime
    converted_at: datetime | None = None

    def assert_active(self, now: datetime) -> None:
        if self.status != "ACTIVE" or self.expires_at <= now:
            raise ServiceDomainError(
                ServiceErrorCode.ALLOCATION_RESERVATION_CONFLICT, "reservation inactive"
            )

    def convert(self, now: datetime) -> AllocationReservation:
        self.assert_active(now)
        return replace(self, status="CONVERTED", converted_at=now)


@dataclass(frozen=True)
class ServiceAttachment:
    attachment_id: UUID
    service_id: UUID
    target: AllocationTarget
    required: bool
    status: AttachmentStatus = AttachmentStatus.RESERVED
    verification_status: str = "PENDING"
    provider_operation_id: UUID | None = None
    remote_identity_reference: str | None = None
    credential_fingerprint: str | None = None
    version: int = 1

    def with_operation(self, operation_id: UUID) -> ServiceAttachment:
        if self.provider_operation_id is not None and self.provider_operation_id != operation_id:
            raise ServiceDomainError(ServiceErrorCode.IDEMPOTENCY_CONFLICT, "operation conflict")
        return replace(
            self,
            provider_operation_id=operation_id,
            status=AttachmentStatus.OPERATION_QUEUED,
            version=self.version + 1,
        )

    def verify(
        self, remote_identity_reference: str, credential_fingerprint: str
    ) -> ServiceAttachment:
        if not remote_identity_reference or "secret" in credential_fingerprint.lower():
            raise ServiceDomainError(
                ServiceErrorCode.PROVISIONING_POSTCONDITION_FAILED, "unsafe proof"
            )
        return replace(
            self,
            remote_identity_reference=remote_identity_reference,
            credential_fingerprint=credential_fingerprint,
            status=AttachmentStatus.VERIFIED,
            verification_status="VERIFIED",
            version=self.version + 1,
        )


@dataclass(frozen=True)
class Service:
    service_id: UUID
    public_reference: str
    entitlement: ServiceEntitlement
    lifecycle: ServiceLifecycle
    attachments: tuple[ServiceAttachment, ...] = ()
    history: tuple[str, ...] = ()
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    activated_at: datetime | None = None

    def transition(self, target: ServiceLifecycle, reason: str) -> Service:
        allowed: dict[ServiceLifecycle, set[ServiceLifecycle]] = {
            ServiceLifecycle.PENDING_ALLOCATION: {
                ServiceLifecycle.ALLOCATED,
                ServiceLifecycle.MANUAL_REVIEW,
            },
            ServiceLifecycle.ALLOCATED: {
                ServiceLifecycle.PROVISIONING,
                ServiceLifecycle.MANUAL_REVIEW,
            },
            ServiceLifecycle.PROVISIONING: {
                ServiceLifecycle.VERIFYING,
                ServiceLifecycle.PROVISIONING_FAILED,
                ServiceLifecycle.MANUAL_REVIEW,
            },
            ServiceLifecycle.VERIFYING: {
                ServiceLifecycle.ACTIVE,
                ServiceLifecycle.DEGRADED,
                ServiceLifecycle.PROVISIONING_FAILED,
                ServiceLifecycle.MANUAL_REVIEW,
            },
            ServiceLifecycle.ACTIVE: {
                ServiceLifecycle.DEGRADED,
                ServiceLifecycle.EXPIRED,
                ServiceLifecycle.MANUAL_REVIEW,
            },
            ServiceLifecycle.DEGRADED: {
                ServiceLifecycle.ACTIVE,
                ServiceLifecycle.MANUAL_REVIEW,
                ServiceLifecycle.EXPIRED,
            },
            ServiceLifecycle.PROVISIONING_FAILED: {
                ServiceLifecycle.PROVISIONING,
                ServiceLifecycle.MANUAL_REVIEW,
            },
            ServiceLifecycle.MANUAL_REVIEW: {
                ServiceLifecycle.PROVISIONING,
                ServiceLifecycle.DEGRADED,
            },
            ServiceLifecycle.EXPIRED: set(),
        }
        if target not in allowed[self.lifecycle]:
            raise ServiceDomainError(ServiceErrorCode.SERVICE_STATE_INVALID, "invalid transition")
        if target is ServiceLifecycle.ACTIVE and not self.required_attachments_verified():
            raise ServiceDomainError(
                ServiceErrorCode.PROVISIONING_PARTIAL_FAILURE, "required attachments not verified"
            )
        return replace(
            self,
            lifecycle=target,
            history=(*self.history, f"{self.lifecycle.value}->{target.value}:{reason}"),
            version=self.version + 1,
            activated_at=datetime.now(UTC)
            if target is ServiceLifecycle.ACTIVE
            else self.activated_at,
        )

    def required_attachments_verified(self) -> bool:
        required = [item for item in self.attachments if item.required]
        return bool(required) and all(item.status is AttachmentStatus.VERIFIED for item in required)


@dataclass(frozen=True)
class FulfillmentRequest:
    request_id: UUID
    deduplication_key: str
    order_id: UUID
    order_item_id: UUID
    unit_index: int
    beneficiary_customer_id: UUID
    payer_reference: str
    status: str = "RECORDED"


def build_fulfillment_request(
    state: CommercialOrderState,
    unit_index: int,
    beneficiary_customer_id: UUID,
    payer_reference: str,
) -> FulfillmentRequest:
    state.assert_eligible()
    key = f"svc-fulfillment:v1:{state.order_id}:{state.order_item_id}:{unit_index}"
    return FulfillmentRequest(
        uuid4(),
        key,
        state.order_id,
        state.order_item_id,
        unit_index,
        beneficiary_customer_id,
        payer_reference,
    )


@dataclass(frozen=True)
class ProvisioningWorkflow:
    workflow_id: UUID
    service_id: UUID
    status: str
    provider_operation_ids: tuple[UUID, ...] = ()

    def record_operation(
        self, operation_id: UUID, status: ProviderOperationStatus
    ) -> ProvisioningWorkflow:
        if status is ProviderOperationStatus.UNCERTAIN:
            return replace(
                self,
                status="MANUAL_REVIEW",
                provider_operation_ids=(*self.provider_operation_ids, operation_id),
            )
        return replace(self, provider_operation_ids=(*self.provider_operation_ids, operation_id))


@dataclass(frozen=True)
class ReconciliationIssue:
    issue_id: UUID
    service_id: UUID
    attachment_id: UUID | None
    outcome: ReconciliationOutcome
    safe_reason_code: str


def reconcile_service(
    service: Service, observed_remote_ids: frozenset[str]
) -> tuple[ReconciliationIssue, ...]:
    issues: list[ReconciliationIssue] = []
    for attachment in service.attachments:
        if attachment.status is AttachmentStatus.VERIFIED:
            if attachment.remote_identity_reference not in observed_remote_ids:
                issues.append(
                    ReconciliationIssue(
                        uuid4(),
                        service.service_id,
                        attachment.attachment_id,
                        ReconciliationOutcome.REMOTE_MISSING,
                        "REMOTE_IDENTITY_MISSING",
                    )
                )
        elif attachment.required:
            issues.append(
                ReconciliationIssue(
                    uuid4(),
                    service.service_id,
                    attachment.attachment_id,
                    ReconciliationOutcome.PARTIALLY_PROVISIONED,
                    "REQUIRED_ATTACHMENT_UNVERIFIED",
                )
            )
    return tuple(issues)


def canonical_service_entitlement(snapshot: dict[str, object]) -> dict[str, object]:
    """Flatten an immutable paid-order snapshot for customer service projections."""
    selected_value = snapshot.get("selected_options")
    if not isinstance(selected_value, dict):
        raise ValueError("paid order selected_options missing")
    selected = cast(dict[str, object], selected_value)
    display_value = snapshot.get("telegram_purchase_display")
    display = cast(dict[str, object], display_value) if isinstance(display_value, dict) else {}
    labels_value = snapshot.get("product_label_snapshot")
    labels = cast(dict[str, object], labels_value) if isinstance(labels_value, dict) else {}
    fa_value = labels.get("fa")
    fa = cast(dict[str, object], fa_value) if isinstance(fa_value, dict) else {}
    values: dict[str, object] = {
        "traffic_quota_bytes": selected.get("traffic_bytes"),
        "duration_days": selected.get("duration_days"),
        "device_limit": selected.get("device_count"),
        "location_code": selected.get("location_code"),
        "quality_code": selected.get("quality_code"),
        "location_label": display.get("location_label") or selected.get("location_code"),
        "quality_label": display.get("quality_label") or selected.get("quality_code"),
        "product_label": display.get("title")
        or fa.get("title")
        or snapshot.get("product_machine_code"),
        "product_version_id": snapshot.get("product_version_id"),
        "required_attachment_count": 1,
    }
    integer_fields = ("traffic_quota_bytes", "duration_days", "device_limit")
    if any(
        type(values[name]) is not int or cast(int, values[name]) <= 0 for name in integer_fields
    ):
        raise ValueError("paid order entitlement is invalid")
    if any(
        not isinstance(values[name], str) or not values[name]
        for name in ("location_code", "quality_code", "product_label")
    ):
        raise ValueError("paid order entitlement labels are invalid")
    return values
