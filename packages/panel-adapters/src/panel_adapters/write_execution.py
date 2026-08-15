"""Production Sanaei provider mutation execution with mandatory reconciliation.

The exact certified Sanaei 3x-ui v3.5.0 CREATE and UPDATE contracts are executable here.
Other providers remain fail-closed until separately certified executors exist.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

import httpx
from vpnsale_domain.providers import (
    MutationPreflightStatus,
    PanelInstance,
    ProviderCertificationStatus,
    ProviderError,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    ProviderRequestContext,
    RemoteIdentifier,
)

from panel_adapters.contracts import SanitizedHttpResponse, SecureHttpTransport
from panel_adapters.sanaei_3x_ui import Sanaei3xUiAdapter
from panel_adapters.write_contracts import preflight_mutation


class MutationOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"
    BLOCKED_BY_CONFIGURATION = "BLOCKED_BY_CONFIGURATION"
    REQUIRES_RECERTIFICATION = "REQUIRES_RECERTIFICATION"
    CONTRACT_MISMATCH = "CONTRACT_MISMATCH"


@dataclass(frozen=True)
class ProviderMutationResult:
    outcome: MutationOutcome
    safe_code: str
    remote_identity: RemoteIdentifier | None = None


class SanaeiMutationTransport(SecureHttpTransport, Protocol):
    async def post_json(
        self, path: str, payload: Mapping[str, object], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse: ...


class SanaeiAuthenticatedTransport:
    """Cookie-session transport which never exposes credentials or raw response bodies."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    @classmethod
    async def authenticate(
        cls,
        validated_base_url: str,
        username: str,
        password: str,
        *,
        verify_tls: bool = True,
        timeout_seconds: float = 10.0,
    ) -> SanaeiAuthenticatedTransport:
        client = httpx.AsyncClient(
            base_url=validated_base_url,
            verify=verify_tls,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
        )
        try:
            response = await client.post(
                "/login", data={"username": username, "password": password}
            )
            body = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else None
            )
            envelope: Mapping[str, object] = (
                cast(Mapping[str, object], body) if isinstance(body, Mapping) else {}
            )
            if response.status_code >= 400 or envelope.get("success") is not True:
                raise PermissionError("provider authentication failed")
        except PermissionError:
            await client.aclose()
            raise
        except (httpx.HTTPError, ValueError) as exc:
            await client.aclose()
            raise ConnectionError("provider authentication unavailable") from exc
        return cls(client)

    @staticmethod
    def _response(response: httpx.Response, started: float) -> SanitizedHttpResponse:
        try:
            body: object | None = response.json()
        except ValueError:
            body = None
        return SanitizedHttpResponse(
            response.status_code,
            body,
            {},
            int((time.monotonic() - started) * 1000),
        )

    async def get(self, path: str, headers: dict[str, str] | None = None) -> SanitizedHttpResponse:
        started = time.monotonic()
        response = await self._client.get(path, headers=headers)
        return self._response(response, started)

    async def post_form(
        self, path: str, form: dict[str, str], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse:
        started = time.monotonic()
        response = await self._client.post(path, data=form, headers=headers)
        return self._response(response, started)

    async def post_json(
        self, path: str, payload: Mapping[str, object], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse:
        started = time.monotonic()
        response = await self._client.post(path, json=dict(payload), headers=headers)
        return self._response(response, started)

    async def aclose(self) -> None:
        await self._client.aclose()


class SanaeiCreateExecutor:
    """Execute the exact v3.5.0 global-client CREATE contract."""

    def __init__(self, transport: SanaeiMutationTransport, panel: PanelInstance) -> None:
        self.transport = transport
        self.panel = panel
        self.adapter = Sanaei3xUiAdapter()

    async def reconcile(self, command: ProviderMutationCommand) -> ProviderMutationResult | None:
        inventory = await self.adapter.fetch_inventory(
            ProviderRequestContext(self.panel, correlation_id=command.correlation_reference),
            self.transport,
        )
        expected = str(command.target_remote_identity or "")
        for client in inventory.clients:
            if (
                str(client.remote_client_identity) == expected
                or client.safe_remark == command.desired_state.provider_safe_label
            ):
                return ProviderMutationResult(
                    MutationOutcome.SUCCESS,
                    "AUTHORITATIVE_RECONCILIATION_MATCH",
                    client.remote_client_identity,
                )
        return None

    async def _safe_reconcile(
        self, command: ProviderMutationCommand
    ) -> tuple[ProviderMutationResult | None, bool]:
        try:
            return await self.reconcile(command), True
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError, ProviderError):
            return None, False

    async def execute(self, command: ProviderMutationCommand) -> ProviderMutationResult:
        if command.operation is not ProviderMutationOperation.CREATE_REMOTE_IDENTITY:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "OPERATION_UNSUPPORTED"
            )
        if len(command.target_inbound_relationships) != 1 or command.target_remote_identity is None:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "AUTHORITATIVE_INBOUND_REQUIRED"
            )
        inbound_raw = str(command.target_inbound_relationships[0])
        try:
            inbound_id = int(inbound_raw)
        except ValueError:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "AUTHORITATIVE_INBOUND_INVALID"
            )
        if inbound_id <= 0:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "AUTHORITATIVE_INBOUND_INVALID"
            )

        existing, reconcile_available = await self._safe_reconcile(command)
        if not reconcile_available:
            return ProviderMutationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_RECONCILIATION_UNAVAILABLE"
            )
        if existing is not None:
            return existing

        desired = command.desired_state
        client: dict[str, object] = {
            "id": str(command.target_remote_identity),
            "email": desired.provider_safe_label,
            "enable": desired.enabled,
            "totalGB": desired.traffic_limit.bytes_limit or 0,
            "expiryTime": (
                int(desired.expiry.expires_at.timestamp() * 1000)
                if desired.expiry.expires_at
                else 0
            ),
            "limitIp": desired.device_or_ip_limit or 0,
            "tgId": 0,
            "subId": command.idempotency_scope[-32:],
            "comment": desired.customer_safe_remark,
        }
        payload: Mapping[str, object] = {"client": client, "inboundIds": [inbound_id]}
        try:
            response = await self.transport.post_json("/panel/api/clients/add", payload)
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return ProviderMutationResult(MutationOutcome.AMBIGUOUS, "PROVIDER_RESPONSE_LOST")

        if response.status_code == 429 or response.status_code >= 500:
            return ProviderMutationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_TEMPORARY_FAILURE"
            )
        if response.status_code in {401, 403}:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_FAILED"
            )

        body = response.json_body
        envelope = cast(Mapping[str, object], body) if isinstance(body, Mapping) else None
        accepted = (
            response.status_code < 400 and envelope is not None and envelope.get("success") is True
        )
        if not accepted:
            reconciled, available = await self._safe_reconcile(command)
            if reconciled is not None:
                return reconciled
            if not available:
                return ProviderMutationResult(
                    MutationOutcome.AMBIGUOUS, "REJECTION_RECONCILIATION_UNAVAILABLE"
                )
            if response.status_code == 429 or response.status_code >= 500:
                return ProviderMutationResult(
                    MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_TEMPORARY_FAILURE"
                )
            if response.status_code >= 400 or envelope is not None:
                return ProviderMutationResult(
                    MutationOutcome.PERMANENT_FAILURE, "PROVIDER_REJECTED_CREATE"
                )
            return ProviderMutationResult(
                MutationOutcome.CONTRACT_MISMATCH, "SUCCESS_ENVELOPE_INVALID"
            )

        verified, available = await self._safe_reconcile(command)
        if not available:
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS, "POST_CREATE_RECONCILIATION_UNAVAILABLE"
            )
        return verified or ProviderMutationResult(
            MutationOutcome.AMBIGUOUS, "READ_AFTER_WRITE_NOT_VERIFIED"
        )


class SanaeiUpdateExecutor:
    """Exact v3.5.0 full-client UPDATE with read-before/write/read-after convergence."""

    def __init__(self, transport: SanaeiMutationTransport, panel: PanelInstance) -> None:
        self.transport = transport
        self.panel = panel

    async def _read_client(self, email: str) -> tuple[Mapping[str, object] | None, bool]:
        try:
            response = await self.transport.get(f"/panel/api/clients/get/{email}")
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return None, False
        if response.status_code in {401, 403, 429} or response.status_code >= 500:
            return None, False
        body = response.json_body
        if not isinstance(body, Mapping):
            return None, False
        envelope = cast(Mapping[str, object], body)
        if envelope.get("success") is not True:
            return None, True
        obj = envelope.get("obj")
        if not isinstance(obj, Mapping):
            return None, False
        client = cast(Mapping[str, object], obj).get("client")
        if not isinstance(client, Mapping):
            return None, False
        return cast(Mapping[str, object], client), True

    @staticmethod
    def _matches(command: ProviderMutationCommand, client: Mapping[str, object]) -> bool:
        desired = command.desired_state
        expiry_ms = (
            int(desired.expiry.expires_at.timestamp() * 1000)
            if desired.expiry.expires_at is not None
            else 0
        )
        expected_identity = str(command.target_remote_identity or "")
        return (
            str(client.get("id") or "") == expected_identity
            and str(client.get("email") or "") == desired.provider_safe_label
            and client.get("enable") is desired.enabled
            and type(client.get("totalGB")) is int
            and int(cast(int, client.get("totalGB"))) == (desired.traffic_limit.bytes_limit or 0)
            and type(client.get("expiryTime")) is int
            and int(cast(int, client.get("expiryTime"))) == expiry_ms
            and type(client.get("limitIp")) is int
            and int(cast(int, client.get("limitIp"))) == (desired.device_or_ip_limit or 0)
        )

    async def fetch_links(self, email: str) -> tuple[str, ...] | None:
        try:
            response = await self.transport.get(f"/panel/api/clients/links/{email}")
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return None
        body: object = response.json_body
        if response.status_code >= 400 or not isinstance(body, Mapping):
            return None
        envelope = cast(Mapping[str, object], body)
        obj = envelope.get("obj")
        if (
            envelope.get("success") is not True
            or not isinstance(obj, Sequence)
            or isinstance(obj, str | bytes)
        ):
            return None
        links: list[str] = []
        for value in cast(Sequence[object], obj):
            if not isinstance(value, str):
                return None
            links.append(value)
        return tuple(links)

    async def execute(self, command: ProviderMutationCommand) -> ProviderMutationResult:
        if command.operation not in {
            ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
            ProviderMutationOperation.ENABLE_REMOTE_IDENTITY,
        }:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "OPERATION_UNSUPPORTED"
            )
        if command.target_remote_identity is None:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "REMOTE_IDENTITY_REQUIRED"
            )
        desired = command.desired_state
        current, available = await self._read_client(desired.provider_safe_label)
        if not available:
            return ProviderMutationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_RECONCILIATION_UNAVAILABLE"
            )
        if current is None:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "REMOTE_CLIENT_MISSING"
            )
        if str(current.get("id") or "") != str(command.target_remote_identity):
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "REMOTE_IDENTITY_MISMATCH"
            )
        if self._matches(command, current):
            return ProviderMutationResult(
                MutationOutcome.SUCCESS,
                "AUTHORITATIVE_RECONCILIATION_MATCH",
                command.target_remote_identity,
            )
        if desired.expiry.expires_at is None:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "ACTIVATION_EXPIRY_REQUIRED"
            )
        payload: Mapping[str, object] = {
            "id": str(command.target_remote_identity),
            "email": desired.provider_safe_label,
            "enable": desired.enabled,
            "totalGB": desired.traffic_limit.bytes_limit or 0,
            "expiryTime": int(desired.expiry.expires_at.timestamp() * 1000),
            "limitIp": desired.device_or_ip_limit or 0,
            "tgId": 0,
            "comment": desired.customer_safe_remark,
        }
        try:
            response = await self.transport.post_json(
                f"/panel/api/clients/update/{desired.provider_safe_label}", payload
            )
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            verified, verify_available = await self._read_client(desired.provider_safe_label)
            if verify_available and verified is not None and self._matches(command, verified):
                return ProviderMutationResult(
                    MutationOutcome.SUCCESS,
                    "RESPONSE_LOST_BUT_RECONCILED",
                    command.target_remote_identity,
                )
            return ProviderMutationResult(MutationOutcome.AMBIGUOUS, "PROVIDER_RESPONSE_LOST")

        body = response.json_body
        envelope = cast(Mapping[str, object], body) if isinstance(body, Mapping) else None
        accepted = (
            response.status_code < 400 and envelope is not None and envelope.get("success") is True
        )
        verified, verify_available = await self._read_client(desired.provider_safe_label)
        if verify_available and verified is not None and self._matches(command, verified):
            return ProviderMutationResult(
                MutationOutcome.SUCCESS,
                "AUTHORITATIVE_RECONCILIATION_MATCH",
                command.target_remote_identity,
            )
        if not verify_available:
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS, "UPDATE_RECONCILIATION_UNAVAILABLE"
            )
        if response.status_code == 429 or response.status_code >= 500:
            return ProviderMutationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_TEMPORARY_FAILURE"
            )
        if response.status_code in {401, 403}:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_FAILED"
            )
        if not accepted:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "PROVIDER_REJECTED_UPDATE"
            )
        return ProviderMutationResult(MutationOutcome.AMBIGUOUS, "READ_AFTER_WRITE_NOT_VERIFIED")


async def _execute_certified_sanaei(
    executor: SanaeiCreateExecutor | SanaeiUpdateExecutor,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> ProviderMutationResult:
    if not writes_enabled:
        return ProviderMutationResult(
            MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_WRITES_DISABLED"
        )
    if panel.provider_kind is not ProviderKind.SANAEI_3X_UI:
        return ProviderMutationResult(
            MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_EXECUTOR_UNSUPPORTED"
        )
    preflight = preflight_mutation(
        panel,
        ProviderKind.SANAEI_3X_UI,
        command,
        detected_version,
        detected_digest,
        certification_status,
    )
    if preflight.status is MutationPreflightStatus.REQUIRES_RECERTIFICATION:
        return ProviderMutationResult(
            MutationOutcome.REQUIRES_RECERTIFICATION, "PROVIDER_RECERTIFICATION_REQUIRED"
        )
    if preflight.status is MutationPreflightStatus.CONTRACT_MISMATCH:
        return ProviderMutationResult(MutationOutcome.CONTRACT_MISMATCH, "CONTRACT_MISMATCH")
    if preflight.status is not MutationPreflightStatus.READY:
        return ProviderMutationResult(
            MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_PREFLIGHT_BLOCKED"
        )
    return await executor.execute(command)


async def execute_certified_sanaei_create(
    executor: SanaeiCreateExecutor,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> ProviderMutationResult:
    return await _execute_certified_sanaei(
        executor,
        panel,
        command,
        writes_enabled=writes_enabled,
        detected_version=detected_version,
        detected_digest=detected_digest,
        certification_status=certification_status,
    )


async def execute_certified_sanaei_update(
    executor: SanaeiUpdateExecutor,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> ProviderMutationResult:
    return await _execute_certified_sanaei(
        executor,
        panel,
        command,
        writes_enabled=writes_enabled,
        detected_version=detected_version,
        detected_digest=detected_digest,
        certification_status=certification_status,
    )
