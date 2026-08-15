from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from platform_api.identity.models import IdentityBase
from platform_api.order_models import JSON_TYPE


class ServiceModel(IdentityBase):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    public_reference: Mapped[str] = mapped_column(String(48), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(40), nullable=False)
    beneficiary_customer_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    payer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payer_reference: Mapped[str] = mapped_column(String(80), nullable=False)
    reseller_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    entitlement_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    allocation_policy_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint("public_reference", name="uq_services_public_reference"),
        UniqueConstraint("order_item_id", "unit_index", name="uq_services_order_item_unit"),
        Index("ix_services_beneficiary_created", "beneficiary_customer_id", "created_at"),
        Index("ix_services_lifecycle_expiry", "lifecycle", "expires_at"),
    )


class ServiceFulfillmentRequestModel(IdentityBase):
    __tablename__ = "service_fulfillment_requests"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    deduplication_key: Mapped[str] = mapped_column(String(160), nullable=False)
    order_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False
    )
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    service_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT")
    )
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(96))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_code: Mapped[str | None] = mapped_column(String(80))
    remote_identity_uuid: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_category: Mapped[str | None] = mapped_column(String(64))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("deduplication_key", name="uq_service_fulfillment_dedupe"),
        UniqueConstraint("order_item_id", "unit_index", name="uq_service_fulfillment_item_unit"),
        Index("ix_service_fulfillment_status_lease", "status", "lease_expires_at"),
    )


class AllocationPolicyModel(IdentityBase):
    __tablename__ = "allocation_policies"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("name", name="uq_allocation_policies_name"),)


class AllocationPolicyVersionModel(IdentityBase):
    __tablename__ = "allocation_policy_versions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    policy_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("allocation_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    success_policy: Mapped[str] = mapped_column(String(40), nullable=False)
    immutable_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "version_number", name="uq_allocation_policy_versions_number"
        ),
    )


class AllocationPoolModel(IdentityBase):
    __tablename__ = "allocation_pools"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("name", name="uq_allocation_pools_name"),)


class AllocationTargetModel(IdentityBase):
    __tablename__ = "allocation_targets"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    pool_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("allocation_pools.id", ondelete="RESTRICT"), nullable=False
    )
    panel_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    node_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    inbound_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    required_protocol: Mapped[str] = mapped_column(String(40), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False)
    max_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    safety_reserve: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    certification_minimum: Mapped[str] = mapped_column(String(80), nullable=False)
    safe_diagnostics: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    __table_args__ = (
        UniqueConstraint(
            "panel_id", "inbound_id", "provider_kind", name="uq_allocation_targets_panel_inbound"
        ),
        CheckConstraint(
            "weight > 0 and max_capacity >= 0 and safety_reserve >= 0",
            name="ck_allocation_targets_capacity",
        ),
        Index("ix_allocation_targets_pool_status", "pool_id", "status"),
    )


class ServiceAttachmentModel(IdentityBase):
    __tablename__ = "service_attachments"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    allocation_target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("allocation_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    remote_identity_reference: Mapped[str | None] = mapped_column(String(160))
    credential_fingerprint: Mapped[str | None] = mapped_column(String(120))
    target_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    observed_state: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint(
            "service_id", "allocation_target_id", name="uq_service_attachments_target"
        ),
        UniqueConstraint(
            "allocation_target_id",
            "remote_identity_reference",
            name="uq_service_attachments_remote_identity",
        ),
        Index("ix_service_attachments_service_status", "service_id", "status"),
    )


class AllocationReservationModel(IdentityBase):
    __tablename__ = "allocation_reservations"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    allocation_target_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("allocation_targets.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reserved_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    reserved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner_reference: Mapped[str] = mapped_column(String(96), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "service_id",
            "allocation_target_id",
            "status",
            name="uq_allocation_reservations_service_target_status",
        ),
        CheckConstraint("reserved_units > 0", name="ck_allocation_reservations_units"),
        Index("ix_allocation_reservations_status_expiry", "status", "expires_at"),
    )


class ProvisioningWorkflowModel(IdentityBase):
    __tablename__ = "service_provisioning_workflows"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (Index("ix_service_workflows_status_updated", "status", "updated_at"),)


class ServiceReconciliationIssueModel(IdentityBase):
    __tablename__ = "service_reconciliation_issues"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    attachment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("service_attachments.id", ondelete="RESTRICT")
    )
    outcome: Mapped[str] = mapped_column(String(48), nullable=False)
    severity: Mapped[str] = mapped_column(String(24), nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    repair_plan: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    compensation_plan: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_service_reconciliation_status_created", "status", "created_at"),)


class ServiceOperationPolicyModel(IdentityBase):
    __tablename__ = "service_operation_policies"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (UniqueConstraint("name", name="uq_service_operation_policies_name"),)


class ServiceOperationPolicyVersionModel(IdentityBase):
    __tablename__ = "service_operation_policy_versions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    policy_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_operation_policies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    immutable_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "version_number", name="uq_service_operation_policy_versions_number"
        ),
    )


class ServiceOperationModel(IdentityBase):
    __tablename__ = "service_operations"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    operation_type: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    requester_type: Mapped[str] = mapped_column(String(32), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(96), nullable=False)
    idempotency_key_digest: Mapped[str] = mapped_column(String(96), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_operation_policy_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    policy_snapshot: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    desired_change: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    quote_snapshot: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE)
    order_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("orders.id", ondelete="RESTRICT")
    )
    invoice_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("invoices.id", ondelete="RESTRICT")
    )
    payment_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("wallet_payments.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        UniqueConstraint(
            "service_id", "idempotency_key_digest", name="uq_service_operations_service_idempotency"
        ),
        Index("ix_service_operations_status_created", "status", "created_at"),
        Index("ix_service_operations_service_created", "service_id", "created_at"),
    )


class ServiceOperationAttachmentPlanModel(IdentityBase):
    __tablename__ = "service_operation_attachment_plans"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    operation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    attachment_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_attachments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(nullable=False)
    provider_operation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    capability: Mapped[str] = mapped_column(String(80), nullable=False)
    expected_snapshot_digest: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    uncertain: Mapped[bool] = mapped_column(nullable=False, default=False)
    result_snapshot: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("operation_id", "attachment_id", name="uq_service_operation_attachment"),
    )


class ServiceStateRevisionModel(IdentityBase):
    __tablename__ = "service_state_revisions"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    service_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False
    )
    operation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    desired_state: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    previous_revision_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("service_id", "revision_number", name="uq_service_state_revisions_number"),
    )


class ServiceOperationApprovalModel(IdentityBase):
    __tablename__ = "service_operation_approvals"
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    operation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("service_operations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(String(96), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(96), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("requested_by <> decided_by", name="ck_service_operation_no_self_approval"),
    )
