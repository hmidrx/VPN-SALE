from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest
from panel_adapters.activation_execution import (
    SanaeiActivationExecutor,
    execute_certified_sanaei_activation,
)
from panel_adapters.contracts import CERTIFIED_CONTRACTS, SanitizedHttpResponse
from panel_adapters.write_execution import MutationOutcome
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelCredentialReference,
    PanelInstance,
    PanelReference,
    ProviderCertificationStatus,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

REMOTE_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
EMAIL = "svc-aaaaaaaaaaaa4aaa8aaa"
EXPIRY = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


class ActivationTransport:
    def __init__(self) -> None:
        self.client: dict[str, object] = {
            "id": REMOTE_UUID,
            "email": EMAIL,
            "enable": False,
            "totalGB": 50 * 1024**3,
            "expiryTime": 0,
            "limitIp": 2,
            "flow": "",
            "subId": "sub-safe",
            "comment": "customer service",
        }
        self.get_paths: list[str] = []
        self.post_paths: list[str] = []
        self.last_payload: dict[str, object] | None = None
        self.raise_after_apply = False

    async def get(self, path: str, headers: dict[str, str] | None = None) -> SanitizedHttpResponse:
        del headers
        self.get_paths.append(path)
        if path == f"/panel/api/clients/get/{EMAIL}":
            return SanitizedHttpResponse(
                200,
                {"success": True, "obj": {"client": dict(self.client), "inboundIds": [1]}},
                {},
                1,
            )
        return SanitizedHttpResponse(404, {"success": False}, {}, 1)

    async def post_form(
        self,
        path: str,
        form: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> SanitizedHttpResponse:
        del path, form, headers
        raise AssertionError("activation must use JSON global-client update")

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, object],
        headers: dict[str, str] | None = None,
    ) -> SanitizedHttpResponse:
        del headers
        self.post_paths.append(path)
        self.last_payload = dict(payload)
        self.client = dict(payload)
        if self.raise_after_apply:
            self.raise_after_apply = False
            raise httpx.ReadTimeout("lost response")
        return SanitizedHttpResponse(200, {"success": True}, {}, 1)


def panel() -> PanelInstance:
    return PanelInstance(
        uuid4(),
        PanelReference("panel-safe"),
        ProviderKind.SANAEI_3X_UI,
        "safe",
        "https://panel.invalid",
        "",
        "enabled",
        PanelCredentialReference(uuid4(), True, "session", "aead-v1"),
    )


def command() -> ProviderMutationCommand:
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    inbound = RemoteIdentifier("1")
    return ProviderMutationCommand(
        UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
        "svc_public",
        "cus_1",
        PanelReference("panel-safe"),
        contract.contract_digest,
        contract.release_tag,
        RemoteIdentifier(REMOTE_UUID),
        (inbound,),
        DesiredRemoteIdentity(
            "svc_public",
            "vless",
            True,
            RemoteTrafficLimit(50 * 1024**3),
            RemoteExpiryPolicy(EXPIRY),
            2,
            "customer service",
            EMAIL,
            (inbound,),
        ),
        "PROVISIONED_DISABLED_NO_EXPIRY",
        "service-activation:v1:svc_public",
        "activation-worker",
        "activate paid service immediately before customer delivery",
        datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        "corr_1",
        "cause_1",
    )


@pytest.mark.asyncio
async def test_activation_uses_exact_v350_global_client_update_contract() -> None:
    transport = ActivationTransport()
    result = await SanaeiActivationExecutor(transport, panel()).execute(command())

    assert result.outcome is MutationOutcome.SUCCESS
    assert result.remote_identity == RemoteIdentifier(REMOTE_UUID)
    assert transport.post_paths == [f"/panel/api/clients/update/{EMAIL}"]
    assert transport.get_paths == [
        f"/panel/api/clients/get/{EMAIL}",
        f"/panel/api/clients/get/{EMAIL}",
    ]
    payload = transport.last_payload
    assert payload is not None
    assert payload["id"] == REMOTE_UUID
    assert payload["email"] == EMAIL
    assert payload["enable"] is True
    assert payload["totalGB"] == 50 * 1024**3
    assert payload["expiryTime"] == int(EXPIRY.timestamp() * 1000)
    assert payload["limitIp"] == 2
    assert payload["subId"] == "sub-safe"


@pytest.mark.asyncio
async def test_lost_activation_response_converges_without_second_update() -> None:
    transport = ActivationTransport()
    transport.raise_after_apply = True
    executor = SanaeiActivationExecutor(transport, panel())

    first = await executor.execute(command())
    assert first.outcome is MutationOutcome.AMBIGUOUS

    second = await executor.execute(command())
    assert second.outcome is MutationOutcome.SUCCESS
    assert second.safe_code == "AUTHORITATIVE_ACTIVATION_MATCH"
    assert transport.post_paths == [f"/panel/api/clients/update/{EMAIL}"]


@pytest.mark.asyncio
async def test_activation_preflight_blocks_all_provider_io_when_writes_disabled() -> None:
    transport = ActivationTransport()
    executor = SanaeiActivationExecutor(transport, panel())
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]

    result = await execute_certified_sanaei_activation(
        executor,
        executor.panel,
        command(),
        writes_enabled=False,
        detected_version=contract.release_tag,
        detected_digest=contract.contract_digest,
        certification_status=ProviderCertificationStatus.CONTRACT_VERIFIED,
    )

    assert result.outcome is MutationOutcome.BLOCKED_BY_CONFIGURATION
    assert transport.post_paths == []
    assert transport.get_paths == []
