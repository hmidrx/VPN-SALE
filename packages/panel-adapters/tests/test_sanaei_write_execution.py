# pyright: reportPrivateUsage=false
from __future__ import annotations

import json
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar

import pytest
from panel_adapters.write_execution import (
    MutationOutcome,
    SanaeiAuthenticatedTransport,
    SanaeiCreateExecutor,
)
from test_provider_write_contracts import _command, _panel
from vpnsale_domain.providers import ProviderKind, ProviderMutationOperation, RemoteIdentifier


class PanelHandler(BaseHTTPRequestHandler):
    clients: ClassVar[list[dict[str, object]]] = []
    creates: ClassVar[int] = 0
    lose_create_response: ClassVar[bool] = False

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
                            "id": "inbound-1",
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
        if self.path.endswith("/addClient/inbound-1"):
            from urllib.parse import parse_qs

            client = json.loads(parse_qs(body)["settings"][0])["clients"][0]
            self.clients.append(client)
            self.__class__.creates += 1
            if self.lose_create_response:
                self.connection.close()
                return
            self._json({"success": True})
            return
        self.send_error(404)


@pytest.fixture
def panel_server():
    PanelHandler.clients = []
    PanelHandler.creates = 0
    PanelHandler.lose_create_response = False
    server = ThreadingHTTPServer(("127.0.0.1", 0), PanelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()


def command():
    value = _command(ProviderMutationOperation.CREATE_REMOTE_IDENTITY, ProviderKind.SANAEI_3X_UI)
    return replace(
        value, target_remote_identity=RemoteIdentifier("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    )


@pytest.mark.asyncio
async def test_real_http_sanaei_create_and_read_after_write(panel_server: str) -> None:
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server, "test", "secret", verify_tls=False
    )
    try:
        result = await SanaeiCreateExecutor(transport, _panel(ProviderKind.SANAEI_3X_UI)).execute(
            command()
        )
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
    executor = SanaeiCreateExecutor(transport, _panel(ProviderKind.SANAEI_3X_UI))
    try:
        first = await executor.execute(command())
        assert first.outcome is MutationOutcome.AMBIGUOUS
        PanelHandler.lose_create_response = False
        second = await executor.execute(command())
    finally:
        await transport.aclose()
    assert second.outcome is MutationOutcome.SUCCESS
    assert PanelHandler.creates == 1
