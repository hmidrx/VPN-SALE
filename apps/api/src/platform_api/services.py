from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from vpnsale_domain.provider_mutations import ProviderWriteMode
from vpnsale_domain.providers import ProviderCertificationStatus, ProviderKind
from vpnsale_domain.services import (
    AllocationPolicyStatus,
    AllocationStrategy,
    IdentityStrategy,
    ServiceDomainError,
    ServiceErrorCode,
    TargetRole,
    select_targets,
)
from vpnsale_domain.services import (
    AllocationPolicyVersion as DomainAllocationPolicyVersion,
)
from vpnsale_domain.services import (
    AllocationTarget as DomainAllocationTarget,
)

from .catalog_models import ProductVersionModel
from .customer_auth.routes import current_customer_session_dependency
from .database import get_db_session
from .identity.models import CustomerSessionModel
from .management import require_perm
from .provider_runtime_models import (
    PanelInstanceModel,
    ProviderConnectionTestModel,
    ProviderInboundSnapshotModel,
)
from .service_models import (
    AllocationPolicyModel,
    AllocationPolicyVersionModel,
    AllocationPoolModel,
    AllocationReservationModel,
    AllocationTargetModel,
    ServiceAttachmentModel,
    ServiceFulfillmentRequestModel,
    ServiceModel,
)
from .usage_models import ServiceUsageAccountModel, ServiceUsageAggregateModel

admin_router = APIRouter(prefix="/api/v1/admin/services", tags=["admin-services"])
customer_router = APIRouter(prefix="/api/v1/customer/services", tags=["customer-services"])
allocation_router = APIRouter(prefix="/api/v1/admin/allocation", tags=["admin-allocation"])
reconciliation_router = APIRouter(
    prefix="/api/v1/admin/service-reconciliation", tags=["admin-service-reconciliation"]
)

_USAGE_MAX_AGE = timedelta(hours=2)


class SafeServiceStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    public_reference: str
    lifecycle: str
    product_label: str = Field(default="خدمت شبکه")
    created_at: datetime
    activated_at: datetime | None
    expires_at: datetime | None
    required_attachment_count: int
    verified_attachment_count: int
    operational_message: str


class CustomerServiceEntitlement(BaseModel):
    traffic_quota_bytes: int | None = None
    duration_days: int | None = None
    device_limit: int | None = None
    location_label: str | None = None
    quality_label: str | None = None


class CustomerServiceUsage(BaseModel):
    used_bytes: int
    total_bytes: int | None
    remaining_bytes: int | None
    last_synced_at: datetime
    unlimited: bool
    stale: bool


class CustomerServiceSummary(BaseModel):
    service_reference: str
    display_name: str
    lifecycle: str
    lifecycle_label: str
    created_at: datetime
    starts_at: datetime | None
    activated_at: datetime | None
    expires_at: datetime | None
    delivery_ready: bool
    required_attachment_count: int
    verified_attachment_count: int
    provisioning_progress: int
    safe_operational_message: str
    entitlement: CustomerServiceEntitlement
    usage: CustomerServiceUsage | None = None


class CustomerServiceDetail(BaseModel):
    summary: CustomerServiceSummary
    service_health: str
    eligible_operations: list[dict[str, object]]
    delivery: dict[str, object]
    latest_activity: list[dict[str, object]]


class FulfillmentRequestStatus(BaseModel):
    id: str
    deduplication_key: str
    order_id: str
    order_item_id: str
    unit_index: int
    status: str
    result_code: str | None


class AllocationPoolCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    status: Literal["ACTIVE", "DISABLED", "MAINTENANCE"] = "ACTIVE"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("invalid pool name")
        return cleaned


class AllocationPoolUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: Literal["ACTIVE", "DISABLED", "MAINTENANCE"] | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("invalid pool name")
        return cleaned


class AllocationPoolResponse(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    target_count: int = 0


class AllocationTargetDiagnosticsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inventory_observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    inventory_max_age_seconds: int = Field(default=900, ge=30, le=86_400)
    healthy: bool = False
    maintenance: bool = False
    write_mode: ProviderWriteMode = ProviderWriteMode.READ_ONLY
    supports_shared_identity: bool = False
    tags: list[str] = Field(default_factory=list, max_length=32)
    provider_version: str = Field(default="", max_length=64)
    contract_digest: str = Field(default="", max_length=96)

    @field_validator("inventory_observed_at")
    @classmethod
    def observed_at_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("inventory observation must include timezone")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            tag = value.strip()
            if not tag or len(tag) > 64 or any(character in tag for character in "\r\n\t:/"):
                raise ValueError("invalid allocation tag")
            cleaned.append(tag)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("duplicate allocation tag")
        return cleaned


class AllocationTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pool_id: UUID
    panel_id: UUID
    node_id: UUID | None = None
    inbound_id: str = Field(min_length=1, max_length=120)
    provider_kind: ProviderKind
    required_protocol: Literal["vless", "vmess", "trojan", "shadowsocks"]
    role: TargetRole = TargetRole.PRIMARY
    priority: int = Field(default=100, ge=0, le=1_000_000)
    weight: int = Field(default=100, ge=1, le=1_000_000)
    max_capacity: int = Field(ge=1, le=100_000_000)
    safety_reserve: int = Field(default=0, ge=0, le=100_000_000)
    status: Literal["ACTIVE", "DISABLED", "MAINTENANCE"] = "ACTIVE"
    certification_minimum: str = Field(min_length=1, max_length=80)
    diagnostics: AllocationTargetDiagnosticsInput = Field(
        default_factory=AllocationTargetDiagnosticsInput
    )

    @field_validator("inbound_id", "certification_minimum")
    @classmethod
    def clean_identifier(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("invalid allocation identifier")
        return cleaned

    @model_validator(mode="after")
    def validate_capacity(self) -> AllocationTargetCreate:
        if self.safety_reserve >= self.max_capacity:
            raise ValueError("safety reserve must be lower than maximum capacity")
        return self


class AllocationTargetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pool_id: UUID | None = None
    panel_id: UUID | None = None
    node_id: UUID | None = None
    inbound_id: str | None = Field(default=None, min_length=1, max_length=120)
    provider_kind: ProviderKind | None = None
    required_protocol: Literal["vless", "vmess", "trojan", "shadowsocks"] | None = None
    role: TargetRole | None = None
    priority: int | None = Field(default=None, ge=0, le=1_000_000)
    weight: int | None = Field(default=None, ge=1, le=1_000_000)
    max_capacity: int | None = Field(default=None, ge=1, le=100_000_000)
    safety_reserve: int | None = Field(default=None, ge=0, le=100_000_000)
    status: Literal["ACTIVE", "DISABLED", "MAINTENANCE"] | None = None
    certification_minimum: str | None = Field(default=None, min_length=1, max_length=80)
    diagnostics: AllocationTargetDiagnosticsInput | None = None

    @field_validator("inbound_id", "certification_minimum")
    @classmethod
    def clean_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("invalid allocation identifier")
        return cleaned


class AllocationTargetResponse(BaseModel):
    id: str
    pool_id: str
    panel_id: str
    node_id: str | None
    inbound_id: str
    provider_kind: str
    required_protocol: str
    role: str
    priority: int
    weight: int
    max_capacity: int
    safety_reserve: int
    status: str
    certification_minimum: str
    diagnostics: AllocationTargetDiagnosticsInput


class AllocationPolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("invalid policy name")
        return cleaned


class AllocationPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    expected_policy_version: int = Field(ge=1)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(character in cleaned for character in "\r\n\t"):
            raise ValueError("invalid policy name")
        return cleaned


class AllocationPolicyResponse(BaseModel):
    id: str
    name: str
    status: str
    current_version_id: str | None
    created_at: datetime
    optimistic_version: int


class AllocationPolicyVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: AllocationStrategy
    success_policy: Literal["ALL_REQUIRED", "AT_LEAST_ONE", "AT_LEAST_N"]
    identity_strategy: IdentityStrategy
    required_target_count: int = Field(ge=1, le=8)
    pool_ids: list[UUID] = Field(min_length=1, max_length=16)
    required_tags: list[str] = Field(default_factory=list, max_length=32)
    product_version_ids: list[UUID] = Field(min_length=1, max_length=128)
    plan_references: list[str] = Field(min_length=1, max_length=128)
    locations: list[str] = Field(default_factory=list, max_length=64)
    required_protocols: list[Literal["vless", "vmess", "trojan", "shadowsocks"]] = Field(
        min_length=1, max_length=4
    )

    @field_validator("required_tags", "plan_references", "locations")
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = value.strip()
            if not item or len(item) > 120 or any(c in item for c in "\r\n\t"):
                raise ValueError("invalid allocation policy value")
            cleaned.append(item)
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("duplicate allocation policy value")
        return cleaned

    @model_validator(mode="after")
    def validate_strategy_count(self) -> AllocationPolicyVersionCreate:
        if self.strategy is AllocationStrategy.SINGLE_TARGET and self.required_target_count != 1:
            raise ValueError("single-target strategy requires exactly one target")
        expected_success_policy = {
            AllocationStrategy.ALL_REQUIRED_TARGETS: "ALL_REQUIRED",
            AllocationStrategy.AT_LEAST_N_TARGETS: "AT_LEAST_N",
        }.get(self.strategy)
        if expected_success_policy is not None and self.success_policy != expected_success_policy:
            raise ValueError("success policy does not match allocation strategy")
        if self.strategy is AllocationStrategy.ONE_PER_GROUP:
            raise ValueError("one-per-group requires explicit group metadata")
        if len(self.pool_ids) != len(set(self.pool_ids)):
            raise ValueError("duplicate allocation pool")
        if len(self.product_version_ids) != len(set(self.product_version_ids)):
            raise ValueError("duplicate product version")
        if len(self.required_protocols) != len(set(self.required_protocols)):
            raise ValueError("duplicate required protocol")
        return self


class AllocationPolicyVersionResponse(BaseModel):
    id: str
    policy_id: str
    version_number: int
    status: str
    strategy: str
    success_policy: str
    identity_strategy: str
    required_target_count: int
    pool_ids: list[str]
    required_tags: list[str]
    product_version_ids: list[str]
    plan_references: list[str]
    locations: list[str]
    required_protocols: list[str]
    published_at: datetime | None
    policy_optimistic_version: int


class AllocationPolicyTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_policy_version: int = Field(ge=1)


class AllocationSimulationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_version_id: UUID
    plan_reference: str = Field(pattern=r"^[a-z][a-z0-9_]{1,78}$")
    location: str | None = Field(default=None, min_length=1, max_length=120)
    required_attachment_count: int = Field(ge=1, le=8)


class AllocationTargetSelection(BaseModel):
    target_id: str
    panel_id: str
    inbound_id: str
    provider_kind: str


class AllocationTargetRejection(BaseModel):
    target_id: str | None
    reason_code: str


class AllocationSimulationResponse(BaseModel):
    eligible: list[str]
    rejected_reason_codes: list[str]
    selected_targets: list[AllocationTargetSelection] = Field(default_factory=list)
    rejected: list[AllocationTargetRejection] = Field(default_factory=list)
    policy_id: str | None = None
    policy_version_id: str | None = None
    performs_reservation: bool = False
    performs_provider_mutation: bool = False


def _allocation_error(code: str, http_status: int = status.HTTP_409_CONFLICT) -> HTTPException:
    return HTTPException(http_status, detail={"code": code})


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _version_parts(value: str) -> tuple[int, ...]:
    normalized = value.strip().lower().removeprefix("v")
    pieces = normalized.split(".")
    if not pieces or any(not piece.isdecimal() for piece in pieces):
        raise _allocation_error(
            "ALLOCATION_CERTIFICATION_VERSION_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return tuple(int(piece) for piece in pieces)


def _pool_response(row: AllocationPoolModel, target_count: int = 0) -> AllocationPoolResponse:
    return AllocationPoolResponse(
        id=row.id,
        name=row.name,
        status=row.status,
        created_at=_aware(row.created_at),
        target_count=target_count,
    )


def _stored_diagnostics(row: AllocationTargetModel) -> AllocationTargetDiagnosticsInput:
    try:
        return AllocationTargetDiagnosticsInput.model_validate(row.safe_diagnostics)
    except ValueError as exc:
        raise _allocation_error(
            "ALLOCATION_TARGET_DIAGNOSTICS_INVALID",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


def _target_response(row: AllocationTargetModel) -> AllocationTargetResponse:
    return AllocationTargetResponse(
        id=row.id,
        pool_id=row.pool_id,
        panel_id=row.panel_id,
        node_id=row.node_id,
        inbound_id=row.inbound_id,
        provider_kind=row.provider_kind,
        required_protocol=row.required_protocol,
        role=row.role,
        priority=row.priority,
        weight=row.weight,
        max_capacity=row.max_capacity,
        safety_reserve=row.safety_reserve,
        status=row.status,
        certification_minimum=row.certification_minimum,
        diagnostics=_stored_diagnostics(row),
    )


def _policy_snapshot(row: AllocationPolicyVersionModel) -> dict[str, object]:
    snapshot = row.immutable_snapshot
    required_keys = {
        "identity_strategy",
        "required_target_count",
        "pool_ids",
        "required_tags",
        "product_version_ids",
        "plan_references",
        "locations",
        "required_protocols",
    }
    if not required_keys.issubset(snapshot):
        raise _allocation_error(
            "ALLOCATION_POLICY_SNAPSHOT_INVALID",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return snapshot


def _string_list(snapshot: dict[str, object], key: str) -> list[str]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        raise _allocation_error(
            "ALLOCATION_POLICY_SNAPSHOT_INVALID",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise _allocation_error(
            "ALLOCATION_POLICY_SNAPSHOT_INVALID",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return [cast(str, item) for item in items]


def _positive_snapshot_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    if type(value) is not int or value < 1:
        raise _allocation_error(
            "ALLOCATION_POLICY_SNAPSHOT_INVALID",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    return value


def _policy_version_response(
    row: AllocationPolicyVersionModel, policy: AllocationPolicyModel
) -> AllocationPolicyVersionResponse:
    snapshot = _policy_snapshot(row)
    return AllocationPolicyVersionResponse(
        id=row.id,
        policy_id=row.policy_id,
        version_number=row.version_number,
        status=row.status,
        strategy=row.strategy,
        success_policy=row.success_policy,
        identity_strategy=str(snapshot["identity_strategy"]),
        required_target_count=_positive_snapshot_int(snapshot, "required_target_count"),
        pool_ids=_string_list(snapshot, "pool_ids"),
        required_tags=_string_list(snapshot, "required_tags"),
        product_version_ids=_string_list(snapshot, "product_version_ids"),
        plan_references=_string_list(snapshot, "plan_references"),
        locations=_string_list(snapshot, "locations"),
        required_protocols=_string_list(snapshot, "required_protocols"),
        published_at=_aware(row.published_at) if row.published_at is not None else None,
        policy_optimistic_version=policy.version,
    )


def _policy_response(row: AllocationPolicyModel) -> AllocationPolicyResponse:
    return AllocationPolicyResponse(
        id=row.id,
        name=row.name,
        status=row.status,
        current_version_id=row.current_version_id,
        created_at=_aware(row.created_at),
        optimistic_version=row.version,
    )


def _latest_target_authority(
    db: Session,
    *,
    panel_id: str,
    provider_kind: str,
    inbound_id: str,
    required_protocol: str,
    certification_minimum: str,
    controls: AllocationTargetDiagnosticsInput,
) -> AllocationTargetDiagnosticsInput:
    panel = db.get(PanelInstanceModel, panel_id)
    if panel is None:
        raise _allocation_error("ALLOCATION_PANEL_NOT_FOUND", status.HTTP_422_UNPROCESSABLE_ENTITY)
    if panel.status.upper() not in {"ACTIVE", "ENABLED"}:
        raise _allocation_error("ALLOCATION_PANEL_NOT_ACTIVE")
    if panel.provider_kind != provider_kind:
        raise _allocation_error(
            "ALLOCATION_PANEL_PROVIDER_MISMATCH",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    if provider_kind != ProviderKind.SANAEI_3X_UI.value:
        raise _allocation_error(
            "ALLOCATION_PROVIDER_NOT_WRITE_CERTIFIED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        if int(inbound_id) <= 0:
            raise ValueError
    except ValueError as exc:
        raise _allocation_error(
            "ALLOCATION_INBOUND_IDENTIFIER_INVALID",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        ) from exc

    certification = db.scalar(
        select(ProviderConnectionTestModel)
        .where(ProviderConnectionTestModel.panel_instance_id == panel_id)
        .order_by(ProviderConnectionTestModel.tested_at.desc())
        .limit(1)
    )
    if (
        certification is None
        or certification.status != ProviderCertificationStatus.CONTRACT_VERIFIED.value
        or not certification.detected_version
        or not certification.contract_digest
    ):
        raise _allocation_error("ALLOCATION_PANEL_CERTIFICATION_REQUIRED")
    if _version_parts(certification.detected_version) < _version_parts(certification_minimum):
        raise _allocation_error("ALLOCATION_PANEL_CERTIFICATION_TOO_OLD")

    inbound = db.scalar(
        select(ProviderInboundSnapshotModel)
        .where(
            ProviderInboundSnapshotModel.panel_instance_id == panel_id,
            ProviderInboundSnapshotModel.remote_identifier == inbound_id,
        )
        .order_by(ProviderInboundSnapshotModel.observed_at.desc())
        .limit(1)
    )
    if inbound is None:
        raise _allocation_error("ALLOCATION_INBOUND_NOT_SYNCED")
    payload = inbound.sanitized_payload
    observed_protocol = payload.get("protocol")
    if not isinstance(observed_protocol, str) or observed_protocol.lower() != required_protocol:
        raise _allocation_error(
            "ALLOCATION_INBOUND_PROTOCOL_MISMATCH",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    inbound_status = (inbound.status or "").upper()
    payload_enabled = payload.get("enabled")
    healthy = payload_enabled is True or inbound_status in {"ACTIVE", "ENABLED", "UP", "HEALTHY"}
    if payload_enabled is False or inbound_status in {"DISABLED", "DOWN", "DELETED"}:
        healthy = False
    return AllocationTargetDiagnosticsInput(
        inventory_observed_at=_aware(inbound.observed_at),
        inventory_max_age_seconds=controls.inventory_max_age_seconds,
        healthy=healthy,
        maintenance=controls.maintenance,
        write_mode=controls.write_mode,
        supports_shared_identity=controls.supports_shared_identity,
        tags=controls.tags,
        provider_version=certification.detected_version,
        contract_digest=certification.contract_digest,
    )


def _active_allocation_counts(db: Session, target_ids: list[str]) -> dict[str, int]:
    if not target_ids:
        return {}
    terminal_statuses = ("FAILED", "DELETED", "RELEASED", "COMPENSATED")
    rows = db.execute(
        select(ServiceAttachmentModel.allocation_target_id, func.count())
        .where(
            ServiceAttachmentModel.allocation_target_id.in_(target_ids),
            ServiceAttachmentModel.status.not_in(terminal_statuses),
        )
        .group_by(ServiceAttachmentModel.allocation_target_id)
    ).all()
    return {str(target_id): int(count) for target_id, count in rows}


def _pending_reservation_counts(
    db: Session, target_ids: list[str], now: datetime
) -> dict[str, int]:
    if not target_ids:
        return {}
    rows = db.execute(
        select(
            AllocationReservationModel.allocation_target_id,
            func.coalesce(func.sum(AllocationReservationModel.reserved_units), 0),
        )
        .where(
            AllocationReservationModel.allocation_target_id.in_(target_ids),
            AllocationReservationModel.status == "ACTIVE",
            AllocationReservationModel.expires_at > now,
        )
        .group_by(AllocationReservationModel.allocation_target_id)
    ).all()
    return {str(target_id): int(count) for target_id, count in rows}


def _domain_policy(row: AllocationPolicyVersionModel) -> DomainAllocationPolicyVersion:
    snapshot = _policy_snapshot(row)
    try:
        return DomainAllocationPolicyVersion(
            policy_id=UUID(row.policy_id),
            version_id=UUID(row.id),
            version_number=row.version_number,
            status=AllocationPolicyStatus(row.status),
            strategy=AllocationStrategy(row.strategy),
            success_policy=row.success_policy,
            identity_strategy=IdentityStrategy(str(snapshot["identity_strategy"])),
            required_target_count=_positive_snapshot_int(snapshot, "required_target_count"),
            required_tags=frozenset(_string_list(snapshot, "required_tags")),
            published_at=_aware(row.published_at) if row.published_at is not None else None,
        )
    except (ValueError, TypeError) as exc:
        raise _allocation_error(
            "ALLOCATION_POLICY_SNAPSHOT_INVALID",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        ) from exc


def _domain_candidates(
    db: Session,
    version: AllocationPolicyVersionModel,
    *,
    now: datetime,
) -> tuple[list[DomainAllocationTarget], list[AllocationTargetRejection]]:
    snapshot = _policy_snapshot(version)
    pool_ids = _string_list(snapshot, "pool_ids")
    protocols = set(_string_list(snapshot, "required_protocols"))
    pools = {
        row.id: row
        for row in db.scalars(
            select(AllocationPoolModel).where(AllocationPoolModel.id.in_(pool_ids))
        )
    }
    targets = list(
        db.scalars(
            select(AllocationTargetModel)
            .where(AllocationTargetModel.pool_id.in_(pool_ids))
            .order_by(AllocationTargetModel.priority, AllocationTargetModel.id)
        )
    )
    target_ids = [row.id for row in targets]
    active_counts = _active_allocation_counts(db, target_ids)
    reservation_counts = _pending_reservation_counts(db, target_ids, now)
    candidates: list[DomainAllocationTarget] = []
    rejected: list[AllocationTargetRejection] = []
    for row in targets:
        pool = pools.get(row.pool_id)
        if pool is None or pool.status != "ACTIVE":
            rejected.append(
                AllocationTargetRejection(
                    target_id=row.id, reason_code="ALLOCATION_POOL_NOT_ACTIVE"
                )
            )
            continue
        if row.status != "ACTIVE":
            rejected.append(
                AllocationTargetRejection(
                    target_id=row.id, reason_code="ALLOCATION_TARGET_NOT_ACTIVE"
                )
            )
            continue
        if row.required_protocol not in protocols:
            rejected.append(
                AllocationTargetRejection(
                    target_id=row.id, reason_code="ALLOCATION_PROTOCOL_NOT_ELIGIBLE"
                )
            )
            continue
        try:
            diagnostics = _latest_target_authority(
                db,
                panel_id=row.panel_id,
                provider_kind=row.provider_kind,
                inbound_id=row.inbound_id,
                required_protocol=row.required_protocol,
                certification_minimum=row.certification_minimum,
                controls=_stored_diagnostics(row),
            )
            candidates.append(
                DomainAllocationTarget(
                    target_id=UUID(row.id),
                    panel_id=UUID(row.panel_id),
                    node_id=UUID(row.node_id) if row.node_id is not None else None,
                    inbound_id=row.inbound_id,
                    provider_kind=row.provider_kind,
                    provider_version=diagnostics.provider_version,
                    contract_digest=diagnostics.contract_digest,
                    role=TargetRole(row.role),
                    priority=row.priority,
                    weight=row.weight,
                    max_capacity=row.max_capacity,
                    safety_reserve=row.safety_reserve,
                    active_allocations=active_counts.get(row.id, 0),
                    pending_reservations=reservation_counts.get(row.id, 0),
                    inventory_observed_at=diagnostics.inventory_observed_at,
                    inventory_max_age=timedelta(seconds=diagnostics.inventory_max_age_seconds),
                    healthy=diagnostics.healthy,
                    maintenance=diagnostics.maintenance,
                    write_mode=diagnostics.write_mode,
                    supports_shared_identity=diagnostics.supports_shared_identity,
                    tags=frozenset(diagnostics.tags),
                )
            )
        except HTTPException as exc:
            detail = exc.detail
            detail_mapping = cast(dict[str, object], detail) if isinstance(detail, dict) else {}
            reason = (
                str(detail_mapping.get("code"))
                if detail_mapping.get("code")
                else "ALLOCATION_TARGET_INVALID"
            )
            rejected.append(AllocationTargetRejection(target_id=row.id, reason_code=reason))
        except (TypeError, ValueError):
            rejected.append(
                AllocationTargetRejection(target_id=row.id, reason_code="ALLOCATION_TARGET_INVALID")
            )
    return candidates, rejected


def _assert_version_selectable(db: Session, row: AllocationPolicyVersionModel) -> None:
    now = datetime.now(UTC)
    candidates, _ = _domain_candidates(db, row, now=now)
    validation_policy = replace(
        _domain_policy(row),
        status=AllocationPolicyStatus.PUBLISHED,
        published_at=now,
    )
    try:
        select_targets(validation_policy, tuple(candidates), f"validate:{row.id}", now)
    except ServiceDomainError as exc:
        raise _allocation_error(exc.code.value) from exc


def resolve_allocation_policy_for_product(
    db: Session,
    *,
    product_version_id: str,
    plan_reference: str,
    location: str | None,
) -> dict[str, object] | None:
    """Resolve the immutable published policy identity captured by a paid quote."""

    versions = db.scalars(
        select(AllocationPolicyVersionModel)
        .where(AllocationPolicyVersionModel.status == AllocationPolicyStatus.PUBLISHED.value)
        .order_by(AllocationPolicyVersionModel.published_at.desc())
    ).all()
    for version in versions:
        snapshot = _policy_snapshot(version)
        if product_version_id not in _string_list(snapshot, "product_version_ids"):
            continue
        if plan_reference not in _string_list(snapshot, "plan_references"):
            continue
        locations = _string_list(snapshot, "locations")
        if locations and (location is None or location not in locations):
            continue
        return {
            "policy_id": version.policy_id,
            "policy_version_id": version.id,
            "policy_version_number": version.version_number,
            "strategy": version.strategy,
            "success_policy": version.success_policy,
            "identity_strategy": str(snapshot["identity_strategy"]),
            "required_target_count": _positive_snapshot_int(snapshot, "required_target_count"),
            "plan_reference": plan_reference,
            "location": location,
        }
    return None


def select_runtime_allocation_targets(
    db: Session,
    *,
    policy_version_id: str,
    decision_key: str,
) -> tuple[AllocationPolicyVersionModel, tuple[AllocationTargetModel, ...]]:
    """Select live targets from one quote-pinned policy without provider mutation.

    A shared multi-inbound identity is intentionally constrained to one panel.  Pools
    may span any number of panels for normal single-target routing, while a plan that
    asks for multiple inbounds must select those inbounds from the same 3x-ui instance.
    """

    version = db.get(AllocationPolicyVersionModel, policy_version_id)
    if version is None or version.status != AllocationPolicyStatus.PUBLISHED.value:
        raise ValueError("allocation policy is unavailable")
    now = datetime.now(UTC)
    candidates, _rejected = _domain_candidates(db, version, now=now)
    try:
        decision = select_targets(_domain_policy(version), tuple(candidates), decision_key, now)
    except ServiceDomainError as exc:
        raise ValueError(exc.code.value) from exc
    selected_ids = [str(item.target_id) for item in decision.selected_targets]
    indexed = {
        row.id: row
        for row in db.scalars(
            select(AllocationTargetModel).where(AllocationTargetModel.id.in_(selected_ids))
        ).all()
    }
    selected = tuple(indexed[target_id] for target_id in selected_ids if target_id in indexed)
    if len(selected) != len(selected_ids):
        raise ValueError("selected allocation target disappeared")
    snapshot = _policy_snapshot(version)
    if len(selected) > 1:
        if str(snapshot["identity_strategy"]) != IdentityStrategy.SHARED.value:
            raise ValueError("multi-inbound allocation requires shared identity")
        if len({row.panel_id for row in selected}) != 1:
            raise ValueError("shared multi-inbound allocation must use one panel")
        if len({row.required_protocol for row in selected}) != 1:
            raise ValueError("shared multi-inbound allocation requires one protocol")
    return version, selected


def snapshot_non_negative_int(value: object, field_name: str, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SERVICE_ENTITLEMENT_INVALID", "field": field_name},
        )
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdecimal():
        parsed = int(value)
    else:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SERVICE_ENTITLEMENT_INVALID", "field": field_name},
        )
    if parsed < 0:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "SERVICE_ENTITLEMENT_INVALID", "field": field_name},
        )
    return parsed


def _safe_service(row: ServiceModel, verified_attachment_count: int = 0) -> SafeServiceStatus:
    entitlement = row.entitlement_snapshot
    required_attachment_count = snapshot_non_negative_int(
        entitlement.get("required_attachment_count"), "required_attachment_count", 0
    )
    return SafeServiceStatus(
        public_reference=row.public_reference,
        lifecycle=row.lifecycle,
        product_label=str(entitlement.get("product_label", "خدمت شبکه")),
        created_at=row.created_at,
        activated_at=row.activated_at,
        expires_at=row.expires_at,
        required_attachment_count=required_attachment_count,
        verified_attachment_count=verified_attachment_count,
        operational_message="وضعیت تحقق سرویس بدون نمایش اطلاعات فنی ارائه‌دهنده.",
    )


_INTEGER_LIMITS = {
    "traffic_quota_bytes": 1024**5,
    "duration_days": 3650,
    "device_limit": 1000,
    "required_attachment_count": 8,
}


def _allowlisted_int(snapshot: dict[str, object], name: str) -> int | None:
    value = snapshot.get(name)
    if type(value) is not int or value < 0 or value > _INTEGER_LIMITS[name]:
        return None
    return value


def _allowlisted_text(snapshot: dict[str, object], name: str, maximum: int) -> str | None:
    value = snapshot.get(name)
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= maximum else None


_LIFECYCLE_LABELS = {
    "ACTIVE": "فعال",
    "PROVISIONING": "در حال آماده‌سازی",
    "PENDING_ACTIVATION": "سفارش ثبت شد",
    "SUSPENDED": "متوقف",
    "EXPIRED": "منقضی",
    "DEGRADED": "نیازمند بررسی",
}


def _fresh_usage(
    db: Session, service_id: str, now: datetime | None = None
) -> CustomerServiceUsage | None:
    account = db.scalar(
        select(ServiceUsageAccountModel).where(ServiceUsageAccountModel.service_id == service_id)
    )
    if account is None:
        return None
    aggregate = db.scalar(
        select(ServiceUsageAggregateModel)
        .where(ServiceUsageAggregateModel.usage_account_id == account.id)
        .order_by(ServiceUsageAggregateModel.calculated_at.desc())
        .limit(1)
    )
    if (
        aggregate is None
        or aggregate.used_bytes is None
        or aggregate.latest_observed_at is None
        or aggregate.confidence not in {"HIGH", "MEDIUM"}
    ):
        return None
    current = now or datetime.now(UTC)
    observed = aggregate.latest_observed_at
    if observed.tzinfo is None:
        return None
    if current - observed > _USAGE_MAX_AGE:
        return None
    return CustomerServiceUsage(
        used_bytes=aggregate.used_bytes,
        total_bytes=account.allowance_bytes,
        remaining_bytes=aggregate.remaining_bytes,
        last_synced_at=observed,
        unlimited=account.is_unlimited,
        stale=False,
    )


def _customer_summary(db: Session, row: ServiceModel, verified: int) -> CustomerServiceSummary:
    snapshot = row.entitlement_snapshot
    required = _allowlisted_int(snapshot, "required_attachment_count") or 0
    entitlement = CustomerServiceEntitlement(
        traffic_quota_bytes=_allowlisted_int(snapshot, "traffic_quota_bytes"),
        duration_days=_allowlisted_int(snapshot, "duration_days"),
        device_limit=_allowlisted_int(snapshot, "device_limit"),
        location_label=_allowlisted_text(snapshot, "location_label", 80),
        quality_label=_allowlisted_text(snapshot, "quality_label", 80),
    )
    progress = min(100, round(verified / required * 100)) if required else 0
    delivery_ready = required > 0 and verified == required and row.lifecycle == "ACTIVE"
    return CustomerServiceSummary(
        service_reference=row.public_reference,
        display_name=_allowlisted_text(snapshot, "product_label", 120) or "خدمت شبکه",
        lifecycle=row.lifecycle,
        lifecycle_label=_LIFECYCLE_LABELS.get(row.lifecycle, "در حال بررسی"),
        created_at=row.created_at,
        starts_at=row.starts_at,
        activated_at=row.activated_at,
        expires_at=row.expires_at,
        delivery_ready=delivery_ready,
        required_attachment_count=required,
        verified_attachment_count=verified,
        provisioning_progress=progress,
        safe_operational_message="وضعیت سرویس بدون نمایش اطلاعات فنی ارائه‌دهنده.",
        entitlement=entitlement,
        usage=_fresh_usage(db, row.id),
    )


def customer_service_summaries(
    db: Session, customer_id: str, limit: int = 50
) -> list[CustomerServiceSummary]:
    """Authoritative customer-safe projection shared by web and private bot APIs."""
    rows = db.scalars(
        select(ServiceModel)
        .where(ServiceModel.beneficiary_customer_id == customer_id)
        .order_by(ServiceModel.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [_customer_summary(db, row, _verified_attachment_count(db, row.id)) for row in rows]


def _verified_attachment_count(db: Session, service_id: str) -> int:
    rows = db.scalars(
        select(ServiceAttachmentModel).where(
            ServiceAttachmentModel.service_id == service_id,
            ServiceAttachmentModel.required.is_(True),
            ServiceAttachmentModel.verification_status == "VERIFIED",
        )
    ).all()
    verified = 0
    for row in rows:
        inbound_ids = row.target_snapshot.get("inbound_ids")
        if isinstance(inbound_ids, list) and inbound_ids:
            verified += len({str(value) for value in cast(list[object], inbound_ids)})
        else:
            verified += 1
    return verified


def customer_service_projection(
    db: Session, customer_id: str, service_reference: str
) -> CustomerServiceDetail | None:
    row = db.scalar(
        select(ServiceModel).where(
            ServiceModel.public_reference == service_reference,
            ServiceModel.beneficiary_customer_id == customer_id,
        )
    )
    if row is None:
        return None
    summary = _customer_summary(db, row, _verified_attachment_count(db, row.id))
    return CustomerServiceDetail(
        summary=summary,
        service_health=summary.lifecycle_label,
        eligible_operations=[],
        delivery={
            "ready": summary.delivery_ready,
            "formats": ["subscription"] if summary.delivery_ready else [],
        },
        latest_activity=[],
    )


@admin_router.get("", response_model=list[SafeServiceStatus])
def list_services(
    _: Annotated[object, Depends(require_perm("services.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[SafeServiceStatus]:
    rows = db.scalars(
        select(ServiceModel).order_by(ServiceModel.created_at.desc()).limit(min(limit, 100))
    )
    return [_safe_service(row) for row in rows]


@admin_router.get("/{service_reference}", response_model=SafeServiceStatus)
def service_detail(
    service_reference: str,
    _: Annotated[object, Depends(require_perm("services.read"))],
    db: Annotated[Session, Depends(get_db_session)],
) -> SafeServiceStatus:
    row = db.scalar(select(ServiceModel).where(ServiceModel.public_reference == service_reference))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    return _safe_service(row)


@admin_router.get("/fulfillment/requests", response_model=list[FulfillmentRequestStatus])
def fulfillment_requests(
    _: Annotated[object, Depends(require_perm("fulfillment.read"))],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[FulfillmentRequestStatus]:
    rows = db.scalars(
        select(ServiceFulfillmentRequestModel)
        .order_by(ServiceFulfillmentRequestModel.created_at.desc())
        .limit(min(limit, 100))
    )
    return [
        FulfillmentRequestStatus(
            id=row.id,
            deduplication_key=row.deduplication_key,
            order_id=row.order_id,
            order_item_id=row.order_item_id,
            unit_index=row.unit_index,
            status=row.status,
            result_code=row.result_code,
        )
        for row in rows
    ]


@customer_router.get("", response_model=list[CustomerServiceSummary])
def customer_services(
    customer_session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 50,
) -> list[CustomerServiceSummary]:
    return customer_service_summaries(db, customer_session.user_id, limit)


@customer_router.get("/{service_reference}", response_model=CustomerServiceDetail)
def customer_service_detail(
    service_reference: str,
    customer_session: Annotated[CustomerSessionModel, Depends(current_customer_session_dependency)],
    db: Annotated[Session, Depends(get_db_session)],
) -> CustomerServiceDetail:
    detail = customer_service_projection(db, customer_session.user_id, service_reference)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail={"code": "SERVICE_NOT_FOUND"})
    return detail


@allocation_router.get("/pools", response_model=list[AllocationPoolResponse])
def list_allocation_pools(
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.read"))],
) -> list[AllocationPoolResponse]:
    rows = db.scalars(select(AllocationPoolModel).order_by(AllocationPoolModel.name)).all()
    count_rows = db.execute(
        select(AllocationTargetModel.pool_id, func.count()).group_by(AllocationTargetModel.pool_id)
    ).all()
    counts = {str(row[0]): int(row[1]) for row in count_rows}
    return [_pool_response(row, int(counts.get(row.id, 0))) for row in rows]


@allocation_router.post(
    "/pools", response_model=AllocationPoolResponse, status_code=status.HTTP_201_CREATED
)
def create_allocation_pool(
    body: AllocationPoolCreate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationPoolResponse:
    row = AllocationPoolModel(
        id=str(uuid4()),
        name=body.name,
        status=body.status,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error("ALLOCATION_POOL_NAME_CONFLICT") from exc
    return _pool_response(row)


@allocation_router.patch("/pools/{pool_id}", response_model=AllocationPoolResponse)
def update_allocation_pool(
    pool_id: UUID,
    body: AllocationPoolUpdate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationPoolResponse:
    row = db.get(AllocationPoolModel, str(pool_id))
    if row is None:
        raise _allocation_error("ALLOCATION_POOL_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error("ALLOCATION_POOL_NAME_CONFLICT") from exc
    count = int(
        db.scalar(
            select(func.count())
            .select_from(AllocationTargetModel)
            .where(AllocationTargetModel.pool_id == row.id)
        )
        or 0
    )
    return _pool_response(row, count)


@allocation_router.get("/targets", response_model=list[AllocationTargetResponse])
def list_allocation_targets(
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.read"))],
    pool_id: UUID | None = None,
) -> list[AllocationTargetResponse]:
    statement = select(AllocationTargetModel)
    if pool_id is not None:
        statement = statement.where(AllocationTargetModel.pool_id == str(pool_id))
    rows = db.scalars(
        statement.order_by(AllocationTargetModel.priority, AllocationTargetModel.id)
    ).all()
    return [_target_response(row) for row in rows]


@allocation_router.post(
    "/targets", response_model=AllocationTargetResponse, status_code=status.HTTP_201_CREATED
)
def create_allocation_target(
    body: AllocationTargetCreate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationTargetResponse:
    if db.get(AllocationPoolModel, str(body.pool_id)) is None:
        raise _allocation_error("ALLOCATION_POOL_NOT_FOUND", status.HTTP_422_UNPROCESSABLE_ENTITY)
    diagnostics = _latest_target_authority(
        db,
        panel_id=str(body.panel_id),
        provider_kind=body.provider_kind.value,
        inbound_id=body.inbound_id,
        required_protocol=body.required_protocol,
        certification_minimum=body.certification_minimum,
        controls=body.diagnostics,
    )
    row = AllocationTargetModel(
        id=str(uuid4()),
        pool_id=str(body.pool_id),
        panel_id=str(body.panel_id),
        node_id=str(body.node_id) if body.node_id is not None else None,
        inbound_id=body.inbound_id,
        provider_kind=body.provider_kind.value,
        required_protocol=body.required_protocol,
        role=body.role.value,
        priority=body.priority,
        weight=body.weight,
        max_capacity=body.max_capacity,
        safety_reserve=body.safety_reserve,
        status=body.status,
        certification_minimum=body.certification_minimum,
        safe_diagnostics=diagnostics.model_dump(mode="json"),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error("ALLOCATION_TARGET_CONFLICT") from exc
    return _target_response(row)


@allocation_router.patch("/targets/{target_id}", response_model=AllocationTargetResponse)
def update_allocation_target(
    target_id: UUID,
    body: AllocationTargetUpdate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationTargetResponse:
    row = db.get(AllocationTargetModel, str(target_id))
    if row is None:
        raise _allocation_error("ALLOCATION_TARGET_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    changes = body.model_dump(exclude_unset=True)
    pool_id = str(changes.get("pool_id", row.pool_id))
    panel_id = str(changes.get("panel_id", row.panel_id))
    if db.get(AllocationPoolModel, pool_id) is None:
        raise _allocation_error("ALLOCATION_POOL_NOT_FOUND", status.HTTP_422_UNPROCESSABLE_ENTITY)
    raw_provider_kind = changes.get("provider_kind", row.provider_kind)
    provider_kind = (
        raw_provider_kind.value
        if isinstance(raw_provider_kind, ProviderKind)
        else str(raw_provider_kind)
    )
    raw_role = changes.get("role", row.role)
    role = raw_role.value if isinstance(raw_role, TargetRole) else str(raw_role)
    diagnostics_input = changes.get("diagnostics")
    if not isinstance(diagnostics_input, AllocationTargetDiagnosticsInput):
        diagnostics_input = _stored_diagnostics(row)
    inbound_id = str(changes.get("inbound_id", row.inbound_id))
    required_protocol = str(changes.get("required_protocol", row.required_protocol))
    certification_minimum = str(changes.get("certification_minimum", row.certification_minimum))
    max_capacity = int(changes.get("max_capacity", row.max_capacity))
    safety_reserve = int(changes.get("safety_reserve", row.safety_reserve))
    if safety_reserve >= max_capacity:
        raise _allocation_error(
            "ALLOCATION_TARGET_CAPACITY_INVALID", status.HTTP_422_UNPROCESSABLE_ENTITY
        )
    diagnostics = _latest_target_authority(
        db,
        panel_id=panel_id,
        provider_kind=provider_kind,
        inbound_id=inbound_id,
        required_protocol=required_protocol,
        certification_minimum=certification_minimum,
        controls=diagnostics_input,
    )
    row.pool_id = pool_id
    row.panel_id = panel_id
    if "node_id" in changes:
        node_id = changes["node_id"]
        row.node_id = str(node_id) if node_id is not None else None
    row.inbound_id = inbound_id
    row.provider_kind = provider_kind
    row.required_protocol = required_protocol
    row.role = role
    row.priority = int(changes.get("priority", row.priority))
    row.weight = int(changes.get("weight", row.weight))
    row.max_capacity = max_capacity
    row.safety_reserve = safety_reserve
    row.status = str(changes.get("status", row.status))
    row.certification_minimum = certification_minimum
    row.safe_diagnostics = diagnostics.model_dump(mode="json")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error("ALLOCATION_TARGET_CONFLICT") from exc
    return _target_response(row)


@allocation_router.get("/policies", response_model=list[AllocationPolicyResponse])
def list_allocation_policies(
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.read"))],
) -> list[AllocationPolicyResponse]:
    rows = db.scalars(select(AllocationPolicyModel).order_by(AllocationPolicyModel.name)).all()
    return [_policy_response(row) for row in rows]


@allocation_router.post(
    "/policies", response_model=AllocationPolicyResponse, status_code=status.HTTP_201_CREATED
)
def create_allocation_policy(
    body: AllocationPolicyCreate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationPolicyResponse:
    row = AllocationPolicyModel(
        id=str(uuid4()),
        name=body.name,
        status=AllocationPolicyStatus.DRAFT.value,
        current_version_id=None,
        created_at=datetime.now(UTC),
        version=1,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error("ALLOCATION_POLICY_NAME_CONFLICT") from exc
    return _policy_response(row)


@allocation_router.patch("/policies/{policy_id}", response_model=AllocationPolicyResponse)
def update_allocation_policy(
    policy_id: UUID,
    body: AllocationPolicyUpdate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationPolicyResponse:
    row = db.scalar(
        select(AllocationPolicyModel)
        .where(AllocationPolicyModel.id == str(policy_id))
        .with_for_update()
    )
    if row is None:
        raise _allocation_error("ALLOCATION_POLICY_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    if row.version != body.expected_policy_version:
        raise _allocation_error(ServiceErrorCode.CONCURRENT_MODIFICATION.value)
    row.name = body.name
    row.version += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error("ALLOCATION_POLICY_NAME_CONFLICT") from exc
    return _policy_response(row)


@allocation_router.get(
    "/policies/{policy_id}/versions", response_model=list[AllocationPolicyVersionResponse]
)
def list_allocation_policy_versions(
    policy_id: UUID,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.read"))],
) -> list[AllocationPolicyVersionResponse]:
    policy = db.get(AllocationPolicyModel, str(policy_id))
    if policy is None:
        raise _allocation_error("ALLOCATION_POLICY_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    rows = db.scalars(
        select(AllocationPolicyVersionModel)
        .where(AllocationPolicyVersionModel.policy_id == policy.id)
        .order_by(AllocationPolicyVersionModel.version_number.desc())
    ).all()
    return [_policy_version_response(row, policy) for row in rows]


@allocation_router.post(
    "/policies/{policy_id}/versions",
    response_model=AllocationPolicyVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_allocation_policy_version(
    policy_id: UUID,
    body: AllocationPolicyVersionCreate,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationPolicyVersionResponse:
    policy = db.scalar(
        select(AllocationPolicyModel)
        .where(AllocationPolicyModel.id == str(policy_id))
        .with_for_update()
    )
    if policy is None:
        raise _allocation_error("ALLOCATION_POLICY_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    pool_ids = [str(value) for value in body.pool_ids]
    known_pools = set(
        db.scalars(select(AllocationPoolModel.id).where(AllocationPoolModel.id.in_(pool_ids))).all()
    )
    if known_pools != set(pool_ids):
        raise _allocation_error("ALLOCATION_POOL_NOT_FOUND", status.HTTP_422_UNPROCESSABLE_ENTITY)
    product_version_ids = [str(value) for value in body.product_version_ids]
    known_product_versions = set(
        db.scalars(
            select(ProductVersionModel.id).where(
                ProductVersionModel.id.in_(product_version_ids),
                ProductVersionModel.status == "PUBLISHED",
            )
        ).all()
    )
    if known_product_versions != set(product_version_ids):
        raise _allocation_error(
            "ALLOCATION_PRODUCT_VERSION_NOT_PUBLISHED",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    latest_number = int(
        db.scalar(
            select(func.max(AllocationPolicyVersionModel.version_number)).where(
                AllocationPolicyVersionModel.policy_id == policy.id
            )
        )
        or 0
    )
    snapshot: dict[str, object] = {
        "identity_strategy": body.identity_strategy.value,
        "required_target_count": body.required_target_count,
        "pool_ids": pool_ids,
        "required_tags": body.required_tags,
        "product_version_ids": product_version_ids,
        "plan_references": body.plan_references,
        "locations": body.locations,
        "required_protocols": body.required_protocols,
    }
    row = AllocationPolicyVersionModel(
        id=str(uuid4()),
        policy_id=policy.id,
        version_number=latest_number + 1,
        status=AllocationPolicyStatus.DRAFT.value,
        strategy=body.strategy.value,
        success_policy=body.success_policy,
        immutable_snapshot=snapshot,
        published_at=None,
    )
    db.add(row)
    policy.version += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _allocation_error(ServiceErrorCode.CONCURRENT_MODIFICATION.value) from exc
    return _policy_version_response(row, policy)


def _locked_policy_and_version(
    db: Session, policy_id: UUID, version_id: UUID
) -> tuple[AllocationPolicyModel, AllocationPolicyVersionModel]:
    policy = db.scalar(
        select(AllocationPolicyModel)
        .where(AllocationPolicyModel.id == str(policy_id))
        .with_for_update()
    )
    if policy is None:
        raise _allocation_error("ALLOCATION_POLICY_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    version = db.scalar(
        select(AllocationPolicyVersionModel).where(
            AllocationPolicyVersionModel.id == str(version_id),
            AllocationPolicyVersionModel.policy_id == policy.id,
        )
    )
    if version is None:
        raise _allocation_error("ALLOCATION_POLICY_VERSION_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return policy, version


@allocation_router.post(
    "/policies/{policy_id}/versions/{version_id}/validate",
    response_model=AllocationPolicyVersionResponse,
)
def validate_allocation_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: AllocationPolicyTransitionRequest,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.manage"))],
) -> AllocationPolicyVersionResponse:
    policy, version = _locked_policy_and_version(db, policy_id, version_id)
    if policy.version != body.expected_policy_version:
        raise _allocation_error(ServiceErrorCode.CONCURRENT_MODIFICATION.value)
    if version.status != AllocationPolicyStatus.DRAFT.value:
        raise _allocation_error("ALLOCATION_POLICY_TRANSITION_INVALID")
    _assert_version_selectable(db, version)
    version.status = AllocationPolicyStatus.VALIDATED.value
    policy.status = AllocationPolicyStatus.VALIDATED.value
    policy.version += 1
    db.commit()
    return _policy_version_response(version, policy)


@allocation_router.post(
    "/policies/{policy_id}/versions/{version_id}/publish",
    response_model=AllocationPolicyVersionResponse,
)
def publish_allocation_policy_version(
    policy_id: UUID,
    version_id: UUID,
    body: AllocationPolicyTransitionRequest,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.publish"))],
) -> AllocationPolicyVersionResponse:
    policy, version = _locked_policy_and_version(db, policy_id, version_id)
    if policy.version != body.expected_policy_version:
        raise _allocation_error(ServiceErrorCode.CONCURRENT_MODIFICATION.value)
    if version.status != AllocationPolicyStatus.VALIDATED.value:
        raise _allocation_error("ALLOCATION_POLICY_TRANSITION_INVALID")
    _assert_version_selectable(db, version)
    now = datetime.now(UTC)
    if policy.current_version_id is not None:
        current = db.get(AllocationPolicyVersionModel, policy.current_version_id)
        if current is not None and current.id != version.id:
            current.status = AllocationPolicyStatus.SUPERSEDED.value
    version.status = AllocationPolicyStatus.PUBLISHED.value
    version.published_at = now
    policy.current_version_id = version.id
    policy.status = AllocationPolicyStatus.PUBLISHED.value
    policy.version += 1
    db.commit()
    return _policy_version_response(version, policy)


@allocation_router.post("/simulate", response_model=AllocationSimulationResponse)
def simulate_allocation(
    body: AllocationSimulationRequest,
    db: Annotated[Session, Depends(get_db_session)],
    _: Annotated[object, Depends(require_perm("allocation.simulate"))],
) -> AllocationSimulationResponse:
    versions = db.scalars(
        select(AllocationPolicyVersionModel)
        .where(AllocationPolicyVersionModel.status == AllocationPolicyStatus.PUBLISHED.value)
        .order_by(AllocationPolicyVersionModel.published_at.desc())
    ).all()
    version: AllocationPolicyVersionModel | None = None
    for candidate in versions:
        snapshot = _policy_snapshot(candidate)
        if str(body.product_version_id) not in _string_list(snapshot, "product_version_ids"):
            continue
        if body.plan_reference not in _string_list(snapshot, "plan_references"):
            continue
        locations = _string_list(snapshot, "locations")
        if body.location is not None and locations and body.location not in locations:
            continue
        if (
            _positive_snapshot_int(snapshot, "required_target_count")
            != body.required_attachment_count
        ):
            continue
        version = candidate
        break
    if version is None:
        return AllocationSimulationResponse(
            eligible=[],
            rejected_reason_codes=["ALLOCATION_POLICY_NOT_FOUND"],
        )
    now = datetime.now(UTC)
    candidates, rejected = _domain_candidates(db, version, now=now)
    try:
        decision = select_targets(
            _domain_policy(version),
            tuple(candidates),
            f"simulate:{body.product_version_id}:{body.plan_reference}:{body.location or '-'}",
            now,
        )
    except ServiceDomainError as exc:
        reasons = [item.reason_code for item in rejected]
        reasons.append(exc.code.value)
        return AllocationSimulationResponse(
            eligible=[],
            rejected_reason_codes=list(dict.fromkeys(reasons)),
            rejected=rejected,
            policy_id=version.policy_id,
            policy_version_id=version.id,
        )
    selected = [
        AllocationTargetSelection(
            target_id=str(target.target_id),
            panel_id=str(target.panel_id),
            inbound_id=target.inbound_id,
            provider_kind=target.provider_kind,
        )
        for target in decision.selected_targets
    ]
    reasons = [item.reason_code for item in rejected]
    reasons.extend(decision.rejected_reason_codes)
    return AllocationSimulationResponse(
        eligible=[item.target_id for item in selected],
        rejected_reason_codes=list(dict.fromkeys(reasons)),
        selected_targets=selected,
        rejected=rejected,
        policy_id=version.policy_id,
        policy_version_id=version.id,
    )


@reconciliation_router.get("/issues", response_model=list[dict[str, str]])
def reconciliation_issues(
    _: Annotated[object, Depends(require_perm("service_reconciliation.read"))],
) -> list[dict[str, str]]:
    return []
