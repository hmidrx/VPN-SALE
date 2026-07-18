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
