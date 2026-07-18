"""Read-only certified adapter for sanaei_3x_ui."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

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
from panel_adapters.parsing import (
    JsonMapping,
    first_present,
    optional_bool,
    optional_epoch_datetime,
    optional_identifier,
    optional_non_negative_int,
    optional_sequence,
    optional_string,
    parse_json_mapping_string,
    require_identifier,
    require_mapping,
    require_sequence,
    require_string,
)


def _enveloped_sequence(body: object, field: str) -> tuple[JsonMapping, ...]:
    if isinstance(body, Sequence) and not isinstance(body, str | bytes):
        source = require_sequence(cast(Sequence[object], body), field)
    else:
        envelope = require_mapping(body, field)
        source = None
        for key in ("obj", "data", "results", "users", "nodes", "inbounds"):
            candidate = optional_sequence(envelope.get(key), f"{field}.{key}")
            if candidate is not None:
                source = candidate
                break
        if source is None:
            raise ProviderError(
                ProviderErrorCode.PROVIDER_RESPONSE_INVALID, f"invalid_list:{field}"
            )
    items: list[JsonMapping] = []
    for index, value in enumerate(source):
        items.append(require_mapping(value, f"{field}[{index}]"))
    return tuple(items)


def _client_sequence(inbound: JsonMapping, field: str) -> tuple[JsonMapping, ...]:
    direct = optional_sequence(inbound.get("clients"), f"{field}.clients")
    stats = optional_sequence(inbound.get("clientStats"), f"{field}.clientStats")
    source = direct if direct is not None else stats
    if source is None:
        settings = parse_json_mapping_string(inbound.get("settings"), f"{field}.settings")
        source = optional_sequence(
            settings.get("clients") if settings is not None else None, f"{field}.settings.clients"
        )
    if source is None:
        return ()
    clients: list[JsonMapping] = []
    for index, value in enumerate(source):
        clients.append(require_mapping(value, f"{field}.clients[{index}]"))
    return tuple(clients)


def _node_snapshot(item: JsonMapping, field: str) -> RemoteNodeSnapshot:
    remote_id = require_identifier(first_present(item, ("id", "uuid", "node_id")), f"{field}.id")
    display_name = (
        optional_string(first_present(item, ("name", "remark", "display_name")), f"{field}.name")
        or "local"
    )
    return RemoteNodeSnapshot(
        RemoteIdentifier(remote_id),
        display_name,
        optional_string(item.get("status"), f"{field}.status"),
        optional_string(item.get("version"), f"{field}.version"),
        optional_string(first_present(item, ("core", "supported_core")), f"{field}.core"),
    )


def _inbound_snapshot(item: JsonMapping, field: str, digest: str) -> RemoteInboundSnapshot:
    stream = parse_json_mapping_string(item.get("streamSettings"), f"{field}.streamSettings")
    inbound_id = require_identifier(
        first_present(item, ("id", "uuid", "inbound_id")), f"{field}.id"
    )
    node_id = optional_identifier(first_present(item, ("node_id", "nodeId")), f"{field}.node_id")
    transport = optional_string(first_present(item, ("transport", "network")), f"{field}.transport")
    security = optional_string(item.get("security"), f"{field}.security")
    if stream is not None:
        transport = transport or optional_string(
            stream.get("network"), f"{field}.streamSettings.network"
        )
        security = security or optional_string(
            stream.get("security"), f"{field}.streamSettings.security"
        )
    listen = optional_string(item.get("listen"), f"{field}.listen")
    return RemoteInboundSnapshot(
        RemoteIdentifier(inbound_id),
        RemoteIdentifier(node_id) if node_id is not None else None,
        optional_string(first_present(item, ("remark", "name")), f"{field}.remark"),
        require_string(item.get("protocol"), f"{field}.protocol"),
        optional_non_negative_int(item.get("port"), f"{field}.port"),
        "explicit" if listen else "any",
        transport,
        security,
        optional_bool(first_present(item, ("enable", "enabled")), f"{field}.enabled"),
        optional_non_negative_int(
            first_present(item, ("client_count", "clientCount")), f"{field}.client_count"
        ),
        optional_non_negative_int(item.get("up"), f"{field}.up"),
        optional_non_negative_int(item.get("down"), f"{field}.down"),
        digest,
    )


def _client_snapshot(
    item: JsonMapping, inbound_id: RemoteIdentifier, field: str, version: str
) -> RemoteClientSnapshot:
    identity = require_identifier(
        first_present(item, ("id", "email", "password", "username")), f"{field}.identity"
    )
    return RemoteClientSnapshot(
        RemoteIdentifier(identity),
        (inbound_id,),
        optional_bool(first_present(item, ("enable", "enabled")), f"{field}.enabled"),
        optional_non_negative_int(
            first_present(item, ("total", "data_limit")), f"{field}.traffic_limit"
        ),
        optional_non_negative_int(item.get("up"), f"{field}.up"),
        optional_non_negative_int(item.get("down"), f"{field}.down"),
        optional_epoch_datetime(
            first_present(item, ("expiryTime", "expiry", "expire")), f"{field}.expiry"
        ),
        optional_bool(item.get("online"), f"{field}.online"),
        optional_string(first_present(item, ("email", "remark")), f"{field}.remark"),
        version,
    )


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
        body = require_mapping(response.json_body, "status")
        version = optional_string(
            first_present(body, ("version", "app_version", "panelVersion")), "status.version"
        )
        status = (
            ProviderCertificationStatus.CONTRACT_VERIFIED
            if version in {self.contract.release_tag, self.contract.release_tag.lstrip("v")}
            else ProviderCertificationStatus.VERSION_UNSUPPORTED
        )
        return PanelVersionDetection(
            ProviderKind.SANAEI_3X_UI,
            version,
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
        if (
            detection.certification_status != ProviderCertificationStatus.CONTRACT_VERIFIED
            or detection.remote_version is None
        ):
            raise ProviderError(
                ProviderErrorCode.PROVIDER_VERSION_UNSUPPORTED,
                "inventory blocked for uncertified contract",
            )
        nodes_response = await transport.get("/panel/api/nodes")
        inbounds_response = await transport.get("/panel/api/inbounds/list")
        nodes = tuple(
            _node_snapshot(item, f"nodes[{index}]")
            for index, item in enumerate(_enveloped_sequence(nodes_response.json_body, "nodes"))
        )
        inbounds: list[RemoteInboundSnapshot] = []
        clients: list[RemoteClientSnapshot] = []
        for index, item in enumerate(_enveloped_sequence(inbounds_response.json_body, "inventory")):
            inbound = _inbound_snapshot(item, f"inventory[{index}]", self.contract.contract_digest)
            inbounds.append(inbound)
            for client_index, client in enumerate(_client_sequence(item, f"inventory[{index}]")):
                clients.append(
                    _client_snapshot(
                        client,
                        inbound.remote_inbound_id,
                        f"inventory[{index}].clients[{client_index}]",
                        detection.remote_version,
                    )
                )
        return RemoteServerSnapshot(
            ProviderKind.SANAEI_3X_UI,
            self.definition,
            detection.remote_version,
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
