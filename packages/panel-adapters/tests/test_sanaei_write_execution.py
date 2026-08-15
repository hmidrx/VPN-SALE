from __future__ import annotations

import json
import threading
from collections.abc import Generator
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


class PanelHandler(BaseHTTPRequestHandler):
    clients: ClassVar[list[dict[str, object]]] = []
    creates: ClassVar[int] = 0
    lose_create_response: ClassVar[bool] = False
    conflict_response: ClassVar[bool] = False

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/panel/api/server/status":
            self._json({"version": "3.5.0"})
        elif self.path == "/panel/api/nodes":
            self._json({"obj": [{"id": "1", "name": "node"}]})
        elif self.path == "/panel/api/inbounds/list":
            self._json(
                {
                    "obj": [
                        {
                            "id": "7",
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
        body = self.rfile.read(length).decode()
        if self.path == "/login":
            self._json({"success": "username=test" in body and "password=secret" in body})
            return
        if self.path == "/panel/api/clients/add":
            payload = cast(dict[str, object], json.loads(body))
            assert payload["inboundIds"] == [7]
            client = cast(dict[str, object], payload["client"])
            if self.conflict_response:
                self.clients.append(client)
                self.send_response(409)
                self.end_headers()
                return
            self.clients.append(client)
            self.__class__.creates += 1
            if self.lose_create_response:
                self.connection.close()
                return
            self._json({"success": True, "obj": None})
            return
        self.send_error(404)


@pytest.fixture
def panel_server() -> Generator[str, None, None]:
    PanelHandler.clients = []
    PanelHandler.creates = 0
    PanelHandler.lose_create_response = False
    PanelHandler.conflict_response = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), PanelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


def panel() -> PanelInstance:
    return PanelInstance(
        uuid4(),
        PanelReference("panel-safe"),
        ProviderKind.SANAEI_3X_UI,
        "safe",
        "http://127.0.0.1",
        "",
        "enabled",
        PanelCredentialReference(uuid4(), True, "session", "aead:v1"),
    )


def command() -> ProviderMutationCommand:
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    identity = RemoteIdentifier("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    inbound = RemoteIdentifier("7")
    return ProviderMutationCommand(
        UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
        "svc_safe",
        "customer_safe",
        PanelReference("panel-safe"),
        "0.6a1",
        contract.release_tag,
        identity,
        (inbound,),
        DesiredRemoteIdentity(
            "shop-safe",
            "vless",
            True,
            RemoteTrafficLimit(1_000_000),
            RemoteExpiryPolicy(datetime(2026, 9, 1, tzinfo=UTC)),
            2,
            "customer safe",
            "service-safe",
            (inbound,),
        ),
        None,
        "fulfillment-safe",
        "worker",
        "paid fulfillment",
        datetime(2026, 8, 15, tzinfo=UTC),
        "correlation-safe",
        None,
    )


@pytest.mark.asyncio
async def test_real_http_sanaei_create_and_read_after_write(panel_server: str) -> None:
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False
    )
    try:
        result = await SanaeiCreateExecutor(transport, panel()).execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
    assert PanelHandler.creates == 1


@pytest.mark.asyncio
async def test_response_loss_reconciles_without_second_create(panel_server: str) -> None:
    PanelHandler.lose_create_response = True
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False
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
async def test_duplicate_conflict_is_reconciled_before_permanent_failure(
    panel_server: str,
) -> None:
    PanelHandler.conflict_response = True
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False
    )
    try:
        result = await SanaeiCreateExecutor(transport, panel()).execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
