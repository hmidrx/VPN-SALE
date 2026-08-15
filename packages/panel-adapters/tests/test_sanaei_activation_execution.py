import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import httpx
from panel_adapters.contracts import SanitizedHttpResponse
from panel_adapters.write_execution import (
    MutationOutcome,
    SanaeiActivationExecutor,
    SanaeiActivationResult,
)


class Transport:
    def __init__(self, *, timeout_update: bool = False) -> None:
        self.timeout_update = timeout_update
        self.active = False
        self.posts = 0
        self.expiry = 0
        self.paths: list[str] = []

    async def get(self, path: str, headers: dict[str, str] | None = None):
        self.paths.append(path)
        if path.endswith("/links/customer-safe"):
            return SanitizedHttpResponse(200, {"success": True, "obj": ["vless://redacted"]}, {}, 1)
        obj: dict[str, object] = {
            "id": "identity",
            "email": "customer-safe",
            "enable": self.active,
            "expiryTime": self.expiry,
        }
        return SanitizedHttpResponse(200, {"success": True, "obj": obj}, {}, 1)

    async def post_form(
        self, path: str, form: dict[str, str], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse:
        raise AssertionError("form endpoint is not part of activation")

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, object],
        headers: dict[str, str] | None = None,
    ) -> SanitizedHttpResponse:
        self.posts += 1
        self.paths.append(path)
        expiry = payload["expiryTime"]
        assert isinstance(expiry, int)
        self.active, self.expiry = True, expiry
        if self.timeout_update:
            raise httpx.ReadTimeout("lost")
        return SanitizedHttpResponse(200, {"success": True}, {}, 1)


def activate(transport: Transport) -> SanaeiActivationResult:
    instant = datetime(2026, 8, 15, tzinfo=UTC)
    return asyncio.run(
        SanaeiActivationExecutor(transport).execute(
            "customer-safe", "identity", instant + timedelta(days=30), instant
        )
    )


def test_activation_success_uses_verified_v350_contract() -> None:
    transport = Transport()
    assert activate(transport).outcome is MutationOutcome.SUCCESS
    assert transport.posts == 1
    assert transport.paths == [
        "/panel/api/clients/get/customer-safe",
        "/panel/api/clients/update/customer-safe",
        "/panel/api/clients/get/customer-safe",
        "/panel/api/clients/links/customer-safe",
    ]


def test_provider_timeout_then_reconciliation_success() -> None:
    transport = Transport(timeout_update=True)
    assert activate(transport).outcome is MutationOutcome.SUCCESS


def test_duplicate_activation_is_reconciled_without_duplicate_update() -> None:
    transport = Transport()
    assert activate(transport).outcome is MutationOutcome.SUCCESS
    assert activate(transport).outcome is MutationOutcome.SUCCESS
    assert transport.posts == 1
