# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar, cast
from uuid import UUID, uuid4

import pytest
from panel_adapters.contracts import CERTIFIED_CONTRACTS
from panel_adapters.write_execution import (
    MutationOutcome,
    SanaeiAuthenticatedTransport,
    SanaeiCreateExecutor,
)
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelCredentialReference,
    PanelInstance,
    PanelReference,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

REMOTE_UUID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class PanelHandler(BaseHTTPRequestHandler):
    clients: ClassVar[list[dict[str, object]]] = []
    creates: ClassVar[int] = 0
    lose_create_response: ClassVar[bool] = False
    reject_create: ClassVar[bool] = False
    last_payload: ClassVar[dict[str, object] | None] = None

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
                            "settings": json.dumps({"clients": self.clients}),
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
        if self.path == "/panel/api/clients/add":
            parsed = json.loads(raw.decode())
            if not isinstance(parsed, dict):
                self._json({"success": False})
                return
            payload = cast(dict[str, object], parsed)
            self.__class__.last_payload = payload
            if self.reject_create:
                self._json({"success": False})
                return
            client_value = payload.get("client")
            inbound_ids = payload.get("inboundIds")
            if not isinstance(client_value, dict) or inbound_ids != [1]:
                self._json({"success": False})
                return
            client = cast(dict[str, object], client_value)
            self.clients.append(client)
            self.__class__.creates += 1
            if self.lose_create_response:
                self.connection.close()
                return
            self._json({"success": True, "msg": "created"})
            return
        self.send_error(404)


@pytest.fixture
def panel_server() -> Iterator[str]:
    PanelHandler.clients = []
    PanelHandler.creates = 0
    PanelHandler.lose_create_response = False
    PanelHandler.reject_create = False
    PanelHandler.last_payload = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), PanelHandler)
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


def command() -> ProviderMutationCommand:
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    inbound = RemoteIdentifier("1")
    return ProviderMutationCommand(
        UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
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
            RemoteTrafficLimit(50 * 1024**3),
            RemoteExpiryPolicy(datetime(2026, 9, 1, tzinfo=UTC)),
            2,
            "customer service",
            "svc-safe-label",
            (inbound,),
        ),
        None,
        "fulfillment-scope-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "fulfillment-worker",
        "paid order fulfillment",
        datetime(2026, 8, 1, tzinfo=UTC),
        "corr_1",
        "cause_1",
    )


@pytest.mark.asyncio
async def test_real_http_sanaei_create_uses_exact_v350_contract_and_read_after_write(
    panel_server: str,
) -> None:
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False  # noqa: S106
    )
    try:
        result = await SanaeiCreateExecutor(transport, panel()).execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
    assert PanelHandler.creates == 1
    payload = PanelHandler.last_payload
    assert payload is not None
    assert payload["inboundIds"] == [1]
    client = cast(dict[str, object], payload["client"])
    assert client["id"] == REMOTE_UUID
    assert client["email"] == "svc-safe-label"
    assert client["totalGB"] == 50 * 1024**3
    assert client["limitIp"] == 2


@pytest.mark.asyncio
async def test_response_loss_reconciles_without_second_create(panel_server: str) -> None:
    PanelHandler.lose_create_response = True
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False  # noqa: S106
    )
    executor = SanaeiCreateExecutor(transport, panel())
    try:
        first = await executor.execute(command())
        assert first.outcome is MutationOutcome.AMBIGUOUS
        PanelHandler.lose_create_response = False
        second = await executor.execute(command())
    finally:
        await transport.aclose()
    assert second.outcome is MutationOutcome.SUCCESS
    assert PanelHandler.creates == 1


@pytest.mark.asyncio
async def test_rejected_create_is_reconciled_before_permanent_failure(panel_server: str) -> None:
    PanelHandler.reject_create = True
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False  # noqa: S106
    )
    try:
        result = await SanaeiCreateExecutor(transport, panel()).execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.PERMANENT_FAILURE
    assert PanelHandler.creates == 0
