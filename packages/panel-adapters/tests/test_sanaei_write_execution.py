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
    execute_certified_sanaei_create,
)
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


class PanelHandler(BaseHTTPRequestHandler):
    clients: ClassVar[list[dict[str, object]]] = []
    creates: ClassVar[int] = 0
    mutation_calls: ClassVar[int] = 0
    lose_create_response: ClassVar[bool] = False
    reject_create: ClassVar[bool] = False
    conflict_after_remote_create: ClassVar[bool] = False
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
            self.__class__.mutation_calls += 1
            parsed = json.loads(raw.decode())
            if not isinstance(parsed, dict):
                self._json({"success": False})
                return
            payload = cast(dict[str, object], parsed)
            self.__class__.last_payload = payload
            client_value = payload.get("client")
            inbound_ids = payload.get("inboundIds")
            if not isinstance(client_value, dict) or inbound_ids != [1]:
                self._json({"success": False})
                return
            client = cast(dict[str, object], client_value)
            if self.conflict_after_remote_create:
                self.clients.append(client)
                self.__class__.creates += 1
                self._json({"success": False, "msg": "already exists"}, status=409)
                return
            if self.reject_create:
                self._json({"success": False}, status=422)
                return
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
    PanelHandler.mutation_calls = 0
    PanelHandler.lose_create_response = False
    PanelHandler.reject_create = False
    PanelHandler.conflict_after_remote_create = False
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


async def _authenticated_executor(
    panel_server: str,
) -> tuple[SanaeiAuthenticatedTransport, SanaeiCreateExecutor]:
    transport = await SanaeiAuthenticatedTransport.authenticate(
        panel_server,
        "test",
        "secret",
        verify_tls=False,  # noqa: S106
    )
    return transport, SanaeiCreateExecutor(transport, panel())


@pytest.mark.asyncio
async def test_real_http_sanaei_create_uses_exact_v350_contract_and_read_after_write(
    panel_server: str,
) -> None:
    transport, executor = await _authenticated_executor(panel_server)
    try:
        result = await executor.execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
    assert PanelHandler.mutation_calls == 1
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
async def test_writes_disabled_performs_zero_provider_mutation_http(panel_server: str) -> None:
    transport, executor = await _authenticated_executor(panel_server)
    contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    try:
        result = await execute_certified_sanaei_create(
            executor,
            executor.panel,
            command(),
            writes_enabled=False,
            detected_version=contract.release_tag,
            detected_digest=contract.contract_digest,
            certification_status=ProviderCertificationStatus.CONTRACT_VERIFIED,
        )
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.BLOCKED_BY_CONFIGURATION
    assert PanelHandler.mutation_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("version", "digest", "expected"),
    [
        ("9.9.9", None, MutationOutcome.REQUIRES_RECERTIFICATION),
        ("3.5.0", "sha256:not-the-certified-contract", MutationOutcome.CONTRACT_MISMATCH),
    ],
)
async def test_certification_or_contract_mismatch_performs_zero_mutation_http(
    panel_server: str,
    version: str,
    digest: str | None,
    expected: MutationOutcome,
) -> None:
    transport, executor = await _authenticated_executor(panel_server)
    try:
        result = await execute_certified_sanaei_create(
            executor,
            executor.panel,
            command(),
            writes_enabled=True,
            detected_version=version,
            detected_digest=digest,
            certification_status=ProviderCertificationStatus.CONTRACT_VERIFIED,
        )
    finally:
        await transport.aclose()
    assert result.outcome is expected
    assert PanelHandler.mutation_calls == 0


@pytest.mark.asyncio
async def test_response_loss_reconciles_without_second_create(panel_server: str) -> None:
    PanelHandler.lose_create_response = True
    transport, executor = await _authenticated_executor(panel_server)
    try:
        first = await executor.execute(command())
        assert first.outcome is MutationOutcome.AMBIGUOUS
        PanelHandler.lose_create_response = False
        second = await executor.execute(command())
    finally:
        await transport.aclose()
    assert second.outcome is MutationOutcome.SUCCESS
    assert PanelHandler.mutation_calls == 1
    assert PanelHandler.creates == 1


@pytest.mark.asyncio
async def test_conflict_response_reconciles_before_permanent_failure(panel_server: str) -> None:
    PanelHandler.conflict_after_remote_create = True
    transport, executor = await _authenticated_executor(panel_server)
    try:
        result = await executor.execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.SUCCESS
    assert result.safe_code == "AUTHORITATIVE_RECONCILIATION_MATCH"
    assert PanelHandler.mutation_calls == 1
    assert PanelHandler.creates == 1


@pytest.mark.asyncio
async def test_rejected_create_is_reconciled_before_permanent_failure(panel_server: str) -> None:
    PanelHandler.reject_create = True
    transport, executor = await _authenticated_executor(panel_server)
    try:
        result = await executor.execute(command())
    finally:
        await transport.aclose()
    assert result.outcome is MutationOutcome.PERMANENT_FAILURE
    assert PanelHandler.mutation_calls == 1
    assert PanelHandler.creates == 0
