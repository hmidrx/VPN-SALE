"""Versioned read-only provider adapter SDK for VPN-SALE."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from dataclasses import dataclass
from typing import Protocol, Self
from urllib.parse import urlparse

from vpnsale_domain.providers import (
    WRITE_CAPABILITIES,
    CapabilitySupport,
    PanelConnectionTest,
    PanelEndpointPolicy,
    PanelTlsPolicy,
    PanelVersionDetection,
    ProviderAdapterVersion,
    ProviderCapability,
    ProviderCapabilityEvidence,
    ProviderContractVersion,
    ProviderError,
    ProviderErrorCode,
    ProviderKind,
    ProviderRequestContext,
    RemoteServerSnapshot,
)

CERTIFIED_CONTRACTS: dict[ProviderKind, ProviderContractVersion] = {
    ProviderKind.SANAEI_3X_UI: ProviderContractVersion(
        upstream_repository="https://github.com/MHSanaei/3x-ui",
        release_tag="v3.5.0",
        commit_sha="4e928a1ce0945a6e956aa63365034ec24d2b1387",
        release_date="2026-07-12",
        contract_digest="sha256:sanaei-3x-ui-v3.5.0-read-only-contract",
        extraction_date="2026-07-18",
    ),
    ProviderKind.ALIREZA_X_UI: ProviderContractVersion(
        upstream_repository="https://github.com/alireza0/x-ui",
        release_tag="v1.11.3",
        commit_sha="419fce7d9b21c2a14c46b99e2a37df731a8c6f9d",
        release_date="2026-07-04",
        contract_digest="sha256:alireza-x-ui-v1.11.3-read-only-contract",
        extraction_date="2026-07-18",
    ),
    ProviderKind.PASARGUARD: ProviderContractVersion(
        upstream_repository="https://github.com/PasarGuard/panel",
        release_tag="v4.0.2",
        commit_sha="0b0ddaa9a5a9a3d7402f5f5a274a1a77f743d4bf",
        release_date="2026-05-17",
        contract_digest="sha256:pasarguard-v4.0.2-read-write-a2a-corrected-contract",
        extraction_date="2026-07-18",
    ),
}


@dataclass(frozen=True)
class PanelHealth:
    healthy: bool
    latency_ms: int | None = None
    version: str | None = None


@dataclass(frozen=True)
class SanitizedHttpResponse:
    status_code: int
    json_body: object | None
    headers: dict[str, str]
    elapsed_ms: int


class SecureHttpTransport(Protocol):
    async def get(
        self, path: str, headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse: ...

    async def post_form(
        self, path: str, form: dict[str, str], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse: ...


class ProviderAdapter(Protocol):
    definition: ProviderAdapterVersion
    contract: ProviderContractVersion
    capabilities: tuple[ProviderCapabilityEvidence, ...]

    async def detect_version(self, transport: SecureHttpTransport) -> PanelVersionDetection: ...

    async def test_connection(
        self, ctx: ProviderRequestContext, transport: SecureHttpTransport
    ) -> PanelConnectionTest: ...

    async def fetch_inventory(
        self, ctx: ProviderRequestContext, transport: SecureHttpTransport
    ) -> RemoteServerSnapshot: ...

    async def mutation_disabled(self, capability: ProviderCapability) -> None: ...


READ_COMMON = (
    ProviderCapability.PANEL_VERSION_READ,
    ProviderCapability.PANEL_HEALTH_READ,
    ProviderCapability.SERVER_STATUS_READ,
    ProviderCapability.INBOUND_LIST,
    ProviderCapability.CLIENT_LIST,
    ProviderCapability.CLIENT_TRAFFIC_READ,
)


def capability_matrix(
    supported: set[ProviderCapability], adapter_version: str, evidence: str
) -> tuple[ProviderCapabilityEvidence, ...]:
    entries: list[ProviderCapabilityEvidence] = []
    for cap in ProviderCapability:
        if cap in WRITE_CAPABILITIES:
            support = CapabilitySupport.DISABLED_BY_POLICY
            reason = "PROVIDER_OPERATION_NOT_ENABLED"
        elif cap in supported:
            support = CapabilitySupport.SUPPORTED
            reason = None
        else:
            support = CapabilitySupport.UNSUPPORTED
            reason = "not_exposed_by_certified_read_only_contract"
        entries.append(ProviderCapabilityEvidence(cap, support, adapter_version, evidence, reason))
    return tuple(entries)


class EndpointValidator:
    def validate(self, raw_url: str, policy: PanelEndpointPolicy, tls: PanelTlsPolicy) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"https", "http"}:
            raise ProviderError(ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "unsupported scheme")
        if policy.require_https and parsed.scheme != "https":
            raise ProviderError(ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "https is required")
        if parsed.username or parsed.password:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "url credentials rejected"
            )
        if not parsed.hostname:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "hostname is required"
            )
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in policy.allowed_ports:
            raise ProviderError(ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "port not permitted")
        infos = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_loopback:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "unsafe endpoint address"
                )
            if ip.is_private and not policy.allow_private_network:
                raise ProviderError(
                    ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED, "private network not trusted"
                )
        if not tls.verify_tls and policy.require_https:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_TLS_VERIFICATION_FAILED, "tls verification required"
            )
        return f"{parsed.scheme}://{parsed.hostname}:{port}{parsed.path.rstrip('/')}"


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class AdapterRegistry:
    adapters: dict[ProviderKind, ProviderAdapter]

    @classmethod
    def default(cls) -> Self:
        from panel_adapters.alireza_x_ui import AlirezaXuiAdapter
        from panel_adapters.pasarguard import PasarGuardAdapter
        from panel_adapters.sanaei_3x_ui import Sanaei3xUiAdapter

        return cls(
            {
                ProviderKind.SANAEI_3X_UI: Sanaei3xUiAdapter(),
                ProviderKind.ALIREZA_X_UI: AlirezaXuiAdapter(),
                ProviderKind.PASARGUARD: PasarGuardAdapter(),
            }
        )

    def certified(self, kind: ProviderKind, version: str, digest: str | None) -> ProviderAdapter:
        adapter = self.adapters[kind]
        if version != adapter.contract.release_tag.lstrip("v") and version != adapter.contract.release_tag:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_VERSION_UNSUPPORTED, "unsupported panel version"
            )
        if digest and digest != adapter.contract.contract_digest:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_CONTRACT_MISMATCH, "contract digest mismatch"
            )
        return adapter
