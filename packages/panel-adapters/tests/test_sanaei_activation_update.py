from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from panel_adapters.contracts import SanitizedHttpResponse
from panel_adapters.write_execution import MutationOutcome, SanaeiUpdateExecutor
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelInstance,
    PanelReference,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

REMOTE_UUID = "11111111-1111-4111-8111-111111111111"
EMAIL = "svc-11111111111141118111"
EXPIRY = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


class UpdateTransport:
    def __init__(self, *, already_active: bool = False, lose_response: bool = False) -> None:
        self.post_paths: list[str] = []
        self.post_payloads: list[dict[str, object]] = []
        self.lose_response = lose_response
        self.client: dict[str, object] = {
            "id": REMOTE_UUID,
            "email": EMAIL,
            "enable": already_active,
            "totalGB": 50 * 1024**3,
            "expiryTime": int(EXPIRY.timestamp() * 1000) if already_active else 0,
            "limitIp": 2,
        }

    async def get(self, path: str, headers: dict[str, str] | None = None) -> SanitizedHttpResponse:
        if path == f"/panel/api/clients/get/{EMAIL}":
            return SanitizedHttpResponse(
                200,
                {"success": True, "obj": {"client": dict(self.client)}},
                {},
                1,
            )
        if path == f"/panel/api/clients/links/{EMAIL}":
            return SanitizedHttpResponse(
                200,
                {"success": True, "obj": ["vless://safe"]},
                {},
                1,
            )
        raise AssertionError(path)

    async def post_form(
        self, path: str, form: dict[str, str], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse:
        raise AssertionError("form mutation not expected")

    async def post_json(
        self, path: str, payload: Mapping[str, object], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse:
        self.post_paths.append(path)
        self.post_payloads.append(dict(payload))
        self.client.update(dict(payload))
        if self.lose_response:
            raise httpx.ReadTimeout("lost provider response")
        return SanitizedHttpResponse(200, {"success": True}, {}, 1)


def panel() -> PanelInstance:
    return PanelInstance(
        UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        PanelReference("panel_test"),
        ProviderKind.SANAEI_3X_UI,
        "test",
        "https://panel.example",
        "",
        "enabled",
    )


def command() -> ProviderMutationCommand:
    return ProviderMutationCommand(
        UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
        "svc_public",
        "customer_public",
        PanelReference("panel_test"),
        "sha256:contract",
        "3.5.0",
        RemoteIdentifier(REMOTE_UUID),
        (RemoteIdentifier("1"),),
        DesiredRemoteIdentity(
            "shop-ref",
            "vless",
            True,
            RemoteTrafficLimit(50 * 1024**3),
            RemoteExpiryPolicy(EXPIRY),
            2,
            "customer service",
            EMAIL,
            (RemoteIdentifier("1"),),
        ),
        "expected-disabled-snapshot",
        "activation-scope",
        "activation-worker",
        "activate",
        datetime.now(UTC),
        "corr",
        "cause",
    )


@pytest.mark.asyncio
async def test_update_uses_exact_v350_route_and_full_activation_fields() -> None:
    transport = UpdateTransport()
    result = await SanaeiUpdateExecutor(transport, panel()).execute(command())

    assert result.outcome is MutationOutcome.SUCCESS
    assert transport.post_paths == [f"/panel/api/clients/update/{EMAIL}"]
    assert transport.post_payloads == [
        {
            "id": REMOTE_UUID,
            "email": EMAIL,
            "enable": True,
            "totalGB": 50 * 1024**3,
            "expiryTime": int(EXPIRY.timestamp() * 1000),
            "limitIp": 2,
            "tgId": 0,
            "comment": "customer service",
        }
    ]


@pytest.mark.asyncio
async def test_already_matching_activation_performs_zero_mutation() -> None:
    transport = UpdateTransport(already_active=True)
    result = await SanaeiUpdateExecutor(transport, panel()).execute(command())

    assert result.outcome is MutationOutcome.SUCCESS
    assert result.safe_code == "AUTHORITATIVE_RECONCILIATION_MATCH"
    assert transport.post_paths == []


@pytest.mark.asyncio
async def test_lost_update_response_converges_without_second_mutation() -> None:
    transport = UpdateTransport(lose_response=True)
    executor = SanaeiUpdateExecutor(transport, panel())

    first = await executor.execute(command())
    assert first.outcome is MutationOutcome.SUCCESS
    assert first.safe_code == "RESPONSE_LOST_BUT_RECONCILED"

    transport.lose_response = False
    second = await executor.execute(command())
    assert second.outcome is MutationOutcome.SUCCESS
    assert len(transport.post_paths) == 1


@pytest.mark.asyncio
async def test_generated_links_require_success_envelope_and_strings() -> None:
    transport = UpdateTransport()
    executor = SanaeiUpdateExecutor(transport, panel())
    assert await executor.fetch_links(EMAIL) == ("vless://safe",)

    async def bad_get(path: str, headers: dict[str, str] | None = None) -> SanitizedHttpResponse:
        return SanitizedHttpResponse(200, {"success": True, "obj": [123]}, {}, 1)

    transport.get = bad_get  # type: ignore[method-assign]
    assert await executor.fetch_links(EMAIL) is None
