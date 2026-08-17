from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, cast
from uuid import UUID, uuid4

import pytest
from panel_adapters.contracts import CERTIFIED_CONTRACTS
from panel_adapters.sanaei_adjust_execution import (
    SanaeiAdjustExecutor,
    execute_certified_sanaei_adjust,
)
from panel_adapters.write_execution import MutationOutcome, SanaeiAuthenticatedTransport
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
BASE_TRAFFIC = 50 * 1024**3
BASE_EXPIRY = datetime(2026, 9, 1, tzinfo=UTC)


class AdjustPanelHandler(BaseHTTPRequestHandler):
    client: ClassVar[dict[str, object]] = {}
    mutation_calls: ClassVar[int] = 0
    last_payload: ClassVar[dict[str, object] | None] = None
    lose_response: ClassVar[bool] = False
    reject_adjustment: ClassVar[bool] = False

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, body: object, status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/panel/api/server/status":
            self._json({"version": "3.5.0"})
        elif self.path == "/panel/api/nodes":
            self._json({"obj": []})
        elif self.path == "/panel/api/inbounds/list":
            self._json(
                {
                    "obj": [
                        {
                            "id": 1,
                            "protocol": "vless",
                            "settings": json.dumps({"clients": [self.client]}),
                        }
                    ]
                }
            )
        else:
            self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        if self.path == "/login":
            body = raw.decode()
            self._json({"success": "username=test" in body and "password=secret" in body})
            return
        if self.path != "/panel/api/clients/bulkAdjust":
            self.send_error(404)
            return
        self.__class__.mutation_calls += 1
        parsed = json.loads(raw.decode())
        if not isinstance(parsed, dict):
            self._json({"success": False}, status=422)
            return
        payload = cast(dict[str, object], parsed)
        self.__class__.last_payload = payload
        if self.reject_adjustment:
            self._json({"success": False}, status=422)
            return
        if payload.get("emails") != ["svc-safe-label"] or payload.get("flow") != "":
            self._json({"success": False}, status=422)
            return
        add_bytes = payload.get("addBytes")
        add_days = payload.get("addDays")
        if not isinstance(add_bytes, int) or not isinstance(add_days, int):
            self._json({"success": False}, status=422)
            return
        current_total = self.client.get("totalGB")
        current_expiry = self.client.get("expiryTime")
        assert isinstance(current_total, int)
        assert isinstance(current_expiry, int)
        self.client["totalGB"] = current_total + add_bytes
        self.client["expiryTime"] = current_expiry + add_days * 24 * 60 * 60 * 1000
        if self.lose_response:
            self.connection.close()
            return
        self._json({"success": True, "obj": {"adjusted": 1}})


@pytest.fixture
def adjust_panel_server() -> Iterator[str]:
    AdjustPanelHandler.client = {
        "id": REMOTE_UUID,
        "email": "svc-safe-label",
        "enable": True,
        "totalGB": BASE_TRAFFIC,
        "expiryTime": int(BASE_EXPIRY.timestamp() * 1000),
    }
    AdjustPanelHandler.mutation_calls = 0
    AdjustPanelHandler.last_payload = None
    AdjustPanelHandler.lose_response = False
    AdjustPanelHandler.reject_adjustment = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), AdjustPanelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


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


def command(
    *, traffic: int = BASE_TRAFFIC, expiry: datetime = BASE_EXPIRY
) -> ProviderMutationCommand:
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    inbound = RemoteIdentifier("1")
    return ProviderMutationCommand(
        UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
        "svc_1",
        "cus_1",
        PanelReference("panel-safe"),
        contract.contract_digest,
        contract.release_tag,
        RemoteIdentifier(REMOTE_UUID),
        (inbound,),
        DesiredRemoteIdentity(
            "shop-id-1",
            "vless",
            True,
            RemoteTrafficLimit(traffic),
            RemoteExpiryPolicy(expiry),
            2,
            "customer service",
            "svc-safe-label",
            (inbound,),
        ),
        None,
        "service-operation-scope-aaaaaaaaaaaaaaaaaaaaaaaa",
        "service-operation-worker",
        "paid service operation",
        datetime(2026, 8, 17, tzinfo=UTC),
        "corr_1",
        "cause_1",
    )


async def authenticated_executor(
    server: str,
) -> tuple[SanaeiAuthenticatedTransport, SanaeiAdjustExecutor]:
    transport = await SanaeiAuthenticatedTransport.authenticate(
        server,
        "test",
        "secret",
        verify_tls=False,  # noqa: S106
    )
    return transport, SanaeiAdjustExecutor(transport, panel())


@pytest.mark.asyncio
async def test_traffic_addon_uses_exact_bulk_adjust_contract_and_totalgb_inventory(
    adjust_panel_server: str,
) -> None:
    transport, executor = await authenticated_executor(adjust_panel_server)
    target = BASE_TRAFFIC + 25 * 1024**3
    try:
        result = await executor.execute(command(traffic=target))
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
    assert AdjustPanelHandler.mutation_calls == 1
    assert AdjustPanelHandler.last_payload == {
        "emails": ["svc-safe-label"],
        "addDays": 0,
        "addBytes": 25 * 1024**3,
        "flow": "",
    }
    assert AdjustPanelHandler.client["totalGB"] == target


@pytest.mark.asyncio
async def test_renewal_uses_whole_day_delta_on_same_client(adjust_panel_server: str) -> None:
    transport, executor = await authenticated_executor(adjust_panel_server)
    target = BASE_EXPIRY + timedelta(days=30)
    try:
        result = await executor.execute(command(expiry=target))
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
    assert AdjustPanelHandler.mutation_calls == 1
    assert AdjustPanelHandler.last_payload == {
        "emails": ["svc-safe-label"],
        "addDays": 30,
        "addBytes": 0,
        "flow": "",
    }
    assert AdjustPanelHandler.client["expiryTime"] == int(target.timestamp() * 1000)


@pytest.mark.asyncio
async def test_lost_response_reconciles_and_retry_never_double_applies(
    adjust_panel_server: str,
) -> None:
    AdjustPanelHandler.lose_response = True
    transport, executor = await authenticated_executor(adjust_panel_server)
    target = BASE_TRAFFIC + 10 * 1024**3
    try:
        first = await executor.execute(command(traffic=target))
        AdjustPanelHandler.lose_response = False
        second = await executor.execute(command(traffic=target))
    finally:
        await transport.aclose()
    assert first.outcome is MutationOutcome.SUCCESS
    assert second.outcome is MutationOutcome.SUCCESS
    assert AdjustPanelHandler.mutation_calls == 1
    assert AdjustPanelHandler.client["totalGB"] == target


@pytest.mark.asyncio
async def test_destructive_adjustment_is_blocked_before_provider_write(
    adjust_panel_server: str,
) -> None:
    transport, executor = await authenticated_executor(adjust_panel_server)
    try:
        result = await executor.execute(command(traffic=BASE_TRAFFIC - 1))
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.BLOCKED_BY_CONFIGURATION
    assert result.safe_code == "DESTRUCTIVE_TRAFFIC_ADJUSTMENT_BLOCKED"
    assert AdjustPanelHandler.mutation_calls == 0


@pytest.mark.asyncio
async def test_certified_gate_blocks_adjustment_when_writes_disabled(
    adjust_panel_server: str,
) -> None:
    transport, executor = await authenticated_executor(adjust_panel_server)
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    try:
        result = await execute_certified_sanaei_adjust(
            executor,
            executor.panel,
            command(traffic=BASE_TRAFFIC + 1024**3),
            writes_enabled=False,
            detected_version=contract.release_tag,
            detected_digest=contract.contract_digest,
            certification_status=ProviderCertificationStatus.CONTRACT_VERIFIED,
        )
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.BLOCKED_BY_CONFIGURATION
    assert AdjustPanelHandler.mutation_calls == 0
