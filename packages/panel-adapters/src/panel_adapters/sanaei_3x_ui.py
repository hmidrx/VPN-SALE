"""Read-only certified adapter for sanaei_3x_ui."""

from __future__ import annotations

from vpnsale_domain.providers import (
    PanelConnectionTest,
    PanelVersionDetection,
    ProviderAdapterVersion,
    ProviderCapability,
    ProviderCertificationStatus,
    ProviderError,
    ProviderErrorCode,
    ProviderHealthCheck,
    ProviderKind,
    ProviderRequestContext,
    RemoteClientSnapshot,
    RemoteIdentifier,
    RemoteInboundSnapshot,
    RemoteNodeSnapshot,
    RemoteServerSnapshot,
)

from panel_adapters.contracts import (
    CERTIFIED_CONTRACTS,
    READ_COMMON,
    SecureHttpTransport,
    capability_matrix,
)


def _list(body: object) -> list[object]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("obj", "data", "results", "users", "nodes", "inbounds"):
            item = body.get(key)
            if isinstance(item, list):
                return item
    return []


def _str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class Sanaei3xUiAdapter:
    definition = ProviderAdapterVersion("sanaei_3x_ui", "0.6a1", ProviderKind.SANAEI_3X_UI)
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    capabilities = capability_matrix(
        set(READ_COMMON)
        | {
            ProviderCapability.NODE_LIST,
            ProviderCapability.CLIENT_ONLINE_READ,
            ProviderCapability.MULTI_NODE_DISCOVERY,
        },
        "0.6a1",
        "docs/provider-contracts/sanaei-3x-ui/v3.5.0/contract.md",
    )

    async def detect_version(self, transport: SecureHttpTransport) -> PanelVersionDetection:
        response = await transport.get("/panel/api/server/status")
        if response.status_code in {401, 403}:
            return PanelVersionDetection(
                ProviderKind.SANAEI_3X_UI,
                None,
                ProviderCertificationStatus.AUTHENTICATION_FAILED,
                None,
                self.definition,
            )
        if not isinstance(response.json_body, dict):
            return PanelVersionDetection(
                ProviderKind.SANAEI_3X_UI,
                None,
                ProviderCertificationStatus.DEGRADED,
                None,
                self.definition,
            )
        version = _str(
            response.json_body.get("version")
            or response.json_body.get("app_version")
            or response.json_body.get("panelVersion")
        )
        status = (
            ProviderCertificationStatus.CONTRACT_VERIFIED
            if version in {self.contract.release_tag, self.contract.release_tag.lstrip("v")}
            else ProviderCertificationStatus.VERSION_UNSUPPORTED
        )
        return PanelVersionDetection(
            ProviderKind.SANAEI_3X_UI,
            version or None,
            status,
            self.contract.contract_digest,
            self.definition,
        )

    async def test_connection(
        self, ctx: ProviderRequestContext, transport: SecureHttpTransport
    ) -> PanelConnectionTest:
        detection = await self.detect_version(transport)
        ok = detection.certification_status == ProviderCertificationStatus.CONTRACT_VERIFIED
        return PanelConnectionTest(
            ok,
            detection.certification_status,
            0,
            detection,
            None
            if ok
            else ProviderError(
                ProviderErrorCode.PROVIDER_VERSION_UNSUPPORTED, "safe diagnostics only"
            ),
        )

    async def fetch_inventory(
        self, ctx: ProviderRequestContext, transport: SecureHttpTransport
    ) -> RemoteServerSnapshot:
        detection = await self.detect_version(transport)
        if detection.certification_status != ProviderCertificationStatus.CONTRACT_VERIFIED:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_VERSION_UNSUPPORTED,
                "inventory blocked for uncertified contract",
            )
        nodes_response = await transport.get("/panel/api/nodes")
        inbounds_response = await transport.get("/panel/api/inbounds/list")
        nodes = tuple(
            RemoteNodeSnapshot(
                RemoteIdentifier(_str(x.get("id") if isinstance(x, dict) else None, "local")),
                _str(x.get("name") if isinstance(x, dict) else None, "local"),
                _str(x.get("status") if isinstance(x, dict) else None) or None,
                _str(x.get("version") if isinstance(x, dict) else None) or None,
                _str(x.get("core") if isinstance(x, dict) else None) or None,
            )
            for x in _list(nodes_response.json_body)
            if isinstance(x, dict)
        )
        inbounds: list[RemoteInboundSnapshot] = []
        clients: list[RemoteClientSnapshot] = []
        for item in _list(inbounds_response.json_body):
            if not isinstance(item, dict):
                continue
            inbound_id = RemoteIdentifier(str(item.get("id", item.get("uuid", "unknown"))))
            inbounds.append(
                RemoteInboundSnapshot(
                    inbound_id,
                    None,
                    _str(item.get("remark") or item.get("name")) or None,
                    _str(item.get("protocol"), "unknown"),
                    _int(item.get("port")),
                    "explicit" if item.get("listen") else "any",
                    _str(item.get("transport") or item.get("network")) or None,
                    _str(item.get("security")) or None,
                    bool(item.get("enable", item.get("enabled", True))),
                    _int(item.get("client_count") or item.get("clientCount")),
                    _int(item.get("up")),
                    _int(item.get("down")),
                    self.contract.contract_digest,
                )
            )
            for c in _list(
                item.get("clients")
                if isinstance(item.get("clients"), list)
                else item.get("clientStats")
            ):
                if isinstance(c, dict):
                    ident = str(
                        c.get("id")
                        or c.get("email")
                        or c.get("password")
                        or c.get("username")
                        or "unknown"
                    )
                    clients.append(
                        RemoteClientSnapshot(
                            RemoteIdentifier(ident),
                            (inbound_id,),
                            bool(c.get("enable", c.get("enabled", True))),
                            _int(c.get("total") or c.get("data_limit")),
                            _int(c.get("up")),
                            _int(c.get("down")),
                            None,
                            c.get("online") if isinstance(c.get("online"), bool) else None,
                            _str(c.get("email") or c.get("remark")) or None,
                            detection.remote_version or "unknown",
                        )
                    )
        return RemoteServerSnapshot(
            ProviderKind.SANAEI_3X_UI,
            self.definition,
            detection.remote_version or "unknown",
            ProviderHealthCheck("ok", 0, None),
            nodes,
            tuple(inbounds),
            tuple(clients),
        )

    async def mutation_disabled(self, capability: ProviderCapability) -> None:
        raise ProviderError(
            ProviderErrorCode.PROVIDER_OPERATION_NOT_ENABLED,
            f"{capability.value} is disabled by Milestone 6-A1 policy",
        )
