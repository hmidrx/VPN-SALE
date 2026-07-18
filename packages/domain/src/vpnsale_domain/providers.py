"""Provider-domain primitives for Milestone 6-A1 read-only VPN panels."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import NewType
from uuid import UUID

PanelReference = NewType("PanelReference", str)
RemoteIdentifier = NewType("RemoteIdentifier", str)


class ProviderKind(StrEnum):
    SANAEI_3X_UI = "sanaei_3x_ui"
    ALIREZA_X_UI = "alireza_x_ui"
    PASARGUARD = "pasarguard"


class ProviderCertificationStatus(StrEnum):
    CONTRACT_VERIFIED = "CONTRACT_VERIFIED"
    LIVE_UNVERIFIED = "LIVE_UNVERIFIED"
    LIVE_VERIFIED = "LIVE_VERIFIED"
    VERSION_UNSUPPORTED = "VERSION_UNSUPPORTED"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    DEGRADED = "DEGRADED"


class ProviderCapability(StrEnum):
    PANEL_VERSION_READ = "PANEL_VERSION_READ"
    PANEL_HEALTH_READ = "PANEL_HEALTH_READ"
    SERVER_STATUS_READ = "SERVER_STATUS_READ"
    NODE_LIST = "NODE_LIST"
    INBOUND_LIST = "INBOUND_LIST"
    CLIENT_LIST = "CLIENT_LIST"
    CLIENT_TRAFFIC_READ = "CLIENT_TRAFFIC_READ"
    CLIENT_ONLINE_READ = "CLIENT_ONLINE_READ"
    CLIENT_IP_READ = "CLIENT_IP_READ"
    HOST_LIST = "HOST_LIST"
    TEMPLATE_LIST = "TEMPLATE_LIST"
    SUBSCRIPTION_METADATA_READ = "SUBSCRIPTION_METADATA_READ"
    MULTI_NODE_DISCOVERY = "MULTI_NODE_DISCOVERY"
    MULTI_INBOUND_DISCOVERY = "MULTI_INBOUND_DISCOVERY"
    HWID_METADATA_READ = "HWID_METADATA_READ"
    FIRST_USE_EXPIRY_DISCOVERY = "FIRST_USE_EXPIRY_DISCOVERY"
    PERIODIC_TRAFFIC_DISCOVERY = "PERIODIC_TRAFFIC_DISCOVERY"
    CLIENT_CREATE = "CLIENT_CREATE"
    CLIENT_UPDATE = "CLIENT_UPDATE"
    CLIENT_ENABLE = "CLIENT_ENABLE"
    CLIENT_DISABLE = "CLIENT_DISABLE"
    CLIENT_DELETE = "CLIENT_DELETE"
    CLIENT_TRAFFIC_RESET = "CLIENT_TRAFFIC_RESET"
    CLIENT_IP_CLEAR = "CLIENT_IP_CLEAR"
    CLIENT_TRAFFIC_LIMIT_UPDATE = "CLIENT_TRAFFIC_LIMIT_UPDATE"
    CLIENT_DEVICE_LIMIT_UPDATE = "CLIENT_DEVICE_LIMIT_UPDATE"
    CLIENT_EXPIRY_UPDATE = "CLIENT_EXPIRY_UPDATE"
    CLIENT_REVOKE_SUBSCRIPTION = "CLIENT_REVOKE_SUBSCRIPTION"
    MULTI_INBOUND_ASSIGNMENT = "MULTI_INBOUND_ASSIGNMENT"


WRITE_CAPABILITIES = frozenset(
    {
        ProviderCapability.CLIENT_CREATE,
        ProviderCapability.CLIENT_UPDATE,
        ProviderCapability.CLIENT_ENABLE,
        ProviderCapability.CLIENT_DISABLE,
        ProviderCapability.CLIENT_DELETE,
        ProviderCapability.CLIENT_TRAFFIC_RESET,
        ProviderCapability.CLIENT_IP_CLEAR,
        ProviderCapability.CLIENT_TRAFFIC_LIMIT_UPDATE,
        ProviderCapability.CLIENT_DEVICE_LIMIT_UPDATE,
        ProviderCapability.CLIENT_EXPIRY_UPDATE,
        ProviderCapability.CLIENT_REVOKE_SUBSCRIPTION,
        ProviderCapability.MULTI_INBOUND_ASSIGNMENT,
    }
)


class CapabilitySupport(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"
    DISABLED_BY_POLICY = "disabled_by_policy"


class ProviderErrorCode(StrEnum):
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    PROVIDER_VERSION_UNSUPPORTED = "PROVIDER_VERSION_UNSUPPORTED"
    PROVIDER_CONTRACT_MISMATCH = "PROVIDER_CONTRACT_MISMATCH"
    PROVIDER_AUTHENTICATION_FAILED = "PROVIDER_AUTHENTICATION_FAILED"
    PROVIDER_AUTHORIZATION_INSUFFICIENT = "PROVIDER_AUTHORIZATION_INSUFFICIENT"
    PROVIDER_ENDPOINT_REJECTED = "PROVIDER_ENDPOINT_REJECTED"
    PROVIDER_TLS_VERIFICATION_FAILED = "PROVIDER_TLS_VERIFICATION_FAILED"
    PROVIDER_CERTIFICATE_PIN_MISMATCH = "PROVIDER_CERTIFICATE_PIN_MISMATCH"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_RESPONSE_TOO_LARGE = "PROVIDER_RESPONSE_TOO_LARGE"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    PROVIDER_CAPABILITY_UNSUPPORTED = "PROVIDER_CAPABILITY_UNSUPPORTED"
    PROVIDER_SYNC_ALREADY_RUNNING = "PROVIDER_SYNC_ALREADY_RUNNING"
    PROVIDER_OPERATION_NOT_ENABLED = "PROVIDER_OPERATION_NOT_ENABLED"
    PROVIDER_WRITE_NOT_ENABLED = "PROVIDER_WRITE_NOT_ENABLED"
    PROVIDER_CREDENTIAL_UNAVAILABLE = "PROVIDER_CREDENTIAL_UNAVAILABLE"
    CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


@dataclass(frozen=True)
class ProviderError(Exception):
    code: ProviderErrorCode
    safe_message: str


@dataclass(frozen=True)
class ProviderAdapterVersion:
    adapter_code: str
    adapter_version: str
    provider_kind: ProviderKind


@dataclass(frozen=True)
class ProviderContractVersion:
    upstream_repository: str
    release_tag: str
    commit_sha: str
    release_date: str
    contract_digest: str
    extraction_date: str


@dataclass(frozen=True)
class ProviderCapabilityEvidence:
    capability: ProviderCapability
    support: CapabilitySupport
    required_adapter_version: str
    evidence_source: str
    reason_code: str | None = None


@dataclass(frozen=True)
class PanelTlsPolicy:
    verify_tls: bool = True
    ca_certificate_reference: str | None = None
    certificate_fingerprint_sha256: str | None = None


@dataclass(frozen=True)
class PanelEndpointPolicy:
    allow_private_network: bool = False
    allowed_ports: frozenset[int] = frozenset({443, 8443})
    require_https: bool = True
    max_response_bytes: int = 2_000_000


@dataclass(frozen=True)
class PanelCredentialReference:
    credential_id: UUID
    configured: bool
    credential_kind: str
    key_version: str


@dataclass(frozen=True)
class PanelInstance:
    id: UUID
    public_reference: PanelReference
    provider_kind: ProviderKind
    display_name: str
    endpoint_origin: str
    base_path: str
    status: str
    credential_reference: PanelCredentialReference | None = None
    tls_policy: PanelTlsPolicy = field(default_factory=PanelTlsPolicy)
    endpoint_policy: PanelEndpointPolicy = field(default_factory=PanelEndpointPolicy)
    optimistic_version: int = 1


@dataclass(frozen=True)
class ProviderRequestContext:
    panel: PanelInstance
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None


@dataclass(frozen=True)
class PanelVersionDetection:
    provider_kind: ProviderKind | None
    remote_version: str | None
    certification_status: ProviderCertificationStatus
    contract_digest: str | None
    adapter: ProviderAdapterVersion | None
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class PanelConnectionTest:
    ok: bool
    status: ProviderCertificationStatus
    latency_ms: int | None
    version_detection: PanelVersionDetection | None
    error: ProviderError | None = None


@dataclass(frozen=True)
class ProviderHealthCheck:
    status: str
    latency_ms: int | None
    clock_skew_seconds: int | None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class RemoteNodeSnapshot:
    remote_node_id: RemoteIdentifier
    display_name: str
    status: str | None
    version: str | None
    supported_core: str | None


@dataclass(frozen=True)
class RemoteInboundSnapshot:
    remote_inbound_id: RemoteIdentifier
    node_remote_id: RemoteIdentifier | None
    remark: str | None
    protocol: str
    port: int | None
    listen_classification: str
    transport: str | None
    security: str | None
    enabled: bool | None
    client_count: int | None
    upload_bytes: int | None
    download_bytes: int | None
    contract_digest: str


@dataclass(frozen=True)
class RemoteClientSnapshot:
    remote_client_identity: RemoteIdentifier
    inbound_remote_ids: tuple[RemoteIdentifier, ...]
    enabled: bool | None
    traffic_limit_bytes: int | None
    upload_bytes: int | None
    download_bytes: int | None
    expiry_at: datetime | None
    online: bool | None
    safe_remark: str | None
    remote_version: str


@dataclass(frozen=True)
class RemoteHostSnapshot:
    remote_host_id: RemoteIdentifier
    display_name: str | None
    template_reference: str | None
    metadata: dict[str, str]


@dataclass(frozen=True)
class RemoteServerSnapshot:
    provider_kind: ProviderKind
    adapter: ProviderAdapterVersion
    remote_version: str
    health: ProviderHealthCheck
    nodes: tuple[RemoteNodeSnapshot, ...]
    inbounds: tuple[RemoteInboundSnapshot, ...]
    clients: tuple[RemoteClientSnapshot, ...]
    hosts: tuple[RemoteHostSnapshot, ...] = ()


@dataclass(frozen=True)
class ProviderDriftIssue:
    issue_code: str
    severity: str
    safe_summary: str
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ProviderSyncRun:
    sync_reference: str
    status: str
    adapter: ProviderAdapterVersion
    started_at: datetime
    completed_at: datetime | None
    drift: tuple[ProviderDriftIssue, ...]


class ProviderMutationOperation(StrEnum):
    CREATE_REMOTE_IDENTITY = "CreateRemoteIdentity"
    UPDATE_REMOTE_IDENTITY = "UpdateRemoteIdentity"
    ENABLE_REMOTE_IDENTITY = "EnableRemoteIdentity"
    DISABLE_REMOTE_IDENTITY = "DisableRemoteIdentity"
    DELETE_REMOTE_IDENTITY = "DeleteRemoteIdentity"
    RESET_REMOTE_TRAFFIC = "ResetRemoteTraffic"
    CLEAR_REMOTE_CLIENT_IPS = "ClearRemoteClientIps"
    SET_REMOTE_TRAFFIC_LIMIT = "SetRemoteTrafficLimit"
    SET_REMOTE_EXPIRY = "SetRemoteExpiry"
    SET_REMOTE_DEVICE_OR_IP_LIMIT = "SetRemoteDeviceOrIpLimit"
    ATTACH_REMOTE_INBOUND = "AttachRemoteInbound"
    DETACH_REMOTE_INBOUND = "DetachRemoteInbound"
    ROTATE_REMOTE_CREDENTIAL = "RotateRemoteCredential"
    REVOKE_REMOTE_SUBSCRIPTION_IDENTITY = "RevokeRemoteSubscriptionIdentity"


class ProviderWriteState(StrEnum):
    DISABLED = "DISABLED"
    CONTRACT_ONLY = "CONTRACT_ONLY"
    MOCK_VERIFIED = "MOCK_VERIFIED"
    LIVE_READ_VERIFIED = "LIVE_READ_VERIFIED"
    LIVE_WRITE_CANARY_REQUIRED = "LIVE_WRITE_CANARY_REQUIRED"
    LIVE_WRITE_VERIFIED = "LIVE_WRITE_VERIFIED"
    SUSPENDED = "SUSPENDED"


class MutationPreflightStatus(StrEnum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    REQUIRES_RECERTIFICATION = "REQUIRES_RECERTIFICATION"
    STALE_REMOTE_STATE = "STALE_REMOTE_STATE"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"


class ProviderOperationState(StrEnum):
    PLANNED = "PLANNED"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"
    READY = "READY"
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass(frozen=True)
class RemoteTrafficLimit:
    bytes_limit: int | None
    unlimited: bool = False

    def __post_init__(self) -> None:
        if self.unlimited == (self.bytes_limit is not None):
            raise ValueError("traffic limit must be either unlimited or an explicit integer")
        if self.bytes_limit is not None and self.bytes_limit < 0:
            raise ValueError("traffic limit cannot be negative")


@dataclass(frozen=True)
class RemoteExpiryPolicy:
    expires_at: datetime | None
    no_expiry: bool = False

    def __post_init__(self) -> None:
        if self.no_expiry == (self.expires_at is not None):
            raise ValueError("expiry must be either no_expiry or an explicit UTC instant")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expiry instant must be timezone-aware")


@dataclass(frozen=True)
class DesiredRemoteIdentity:
    shop_identity_reference: str
    protocol: str
    enabled: bool
    traffic_limit: RemoteTrafficLimit
    expiry: RemoteExpiryPolicy
    device_or_ip_limit: int | None
    customer_safe_remark: str
    provider_safe_label: str
    inbound_assignments: tuple[RemoteIdentifier, ...]
    credential_fingerprint: str | None = None
    provider_options_digest: str | None = None


@dataclass(frozen=True)
class ProviderMutationCommand:
    operation_id: UUID
    operation: ProviderMutationOperation
    service_reference: str
    customer_reference: str
    panel_reference: PanelReference
    adapter_contract_version: str
    expected_panel_version: str
    target_remote_identity: RemoteIdentifier | None
    target_inbound_relationships: tuple[RemoteIdentifier, ...]
    desired_state: DesiredRemoteIdentity
    expected_remote_snapshot: str | None
    idempotency_scope: str
    actor_reference: str
    reason: str
    requested_at: datetime
    correlation_reference: str
    causation_reference: str | None


@dataclass(frozen=True)
class MutationPreflightResult:
    status: MutationPreflightStatus
    operation: ProviderMutationOperation
    capability: ProviderCapability | None
    safe_reasons: tuple[str, ...]


@dataclass(frozen=True)
class DryRunMutationPlan:
    provider: ProviderKind
    adapter_contract_version: str
    operation: ProviderMutationOperation
    target_panel: PanelReference
    target_remote_resource: RemoteIdentifier | None
    affected_inbound_relationships: tuple[RemoteIdentifier, ...]
    changed_fields: tuple[str, ...]
    capability_evidence: tuple[ProviderCapabilityEvidence, ...]
    sanitized_endpoint_identifier: str
    expected_response_class: str
    expected_postconditions: tuple[str, ...]
    read_after_write_checks: tuple[str, ...]
    compensation_strategy: str
    retry_classification: str
    risk_classification: str
    warnings: tuple[str, ...]
    expires_at: datetime
    plan_digest: str
