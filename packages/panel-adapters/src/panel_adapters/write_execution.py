"""Production provider mutation execution with mandatory reconciliation.

Only the certified Sanaei CREATE operation is executable.  Other providers fail
closed rather than borrowing superficially similar endpoints.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
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


class SanaeiWriteTransport(SecureHttpTransport, Protocol):
    async def post_json(
        self, path: str, payload: dict[str, object], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse: ...


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


class SanaeiAuthenticatedTransport:
    """Cookie-session transport which never exposes credentials or response bodies."""

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
                await client.aclose()
                raise PermissionError("provider authentication failed")
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
        self, path: str, payload: dict[str, object], headers: dict[str, str] | None = None
    ) -> SanitizedHttpResponse:
        started = time.monotonic()
        response = await self._client.post(path, json=payload, headers=headers)
        return self._response(response, started)

    async def aclose(self) -> None:
        await self._client.aclose()


class SanaeiCreateExecutor:
    """Execute the v3.5.0 add-client contract through an authenticated transport."""

    def __init__(self, transport: SanaeiWriteTransport, panel: PanelInstance) -> None:
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

    async def execute(self, command: ProviderMutationCommand) -> ProviderMutationResult:
        if command.operation is not ProviderMutationOperation.CREATE_REMOTE_IDENTITY:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "OPERATION_UNSUPPORTED"
            )
        if len(command.target_inbound_relationships) != 1 or command.target_remote_identity is None:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "AUTHORITATIVE_INBOUND_REQUIRED"
            )
        try:
            existing = await self.reconcile(command)
        except (httpx.TimeoutException, httpx.NetworkError, ProviderError):
            return ProviderMutationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_RECONCILIATION_UNAVAILABLE"
            )
        if existing:
            return existing
        desired = command.desired_state
        client = {
            "id": str(command.target_remote_identity),
            "email": desired.provider_safe_label,
            "enable": desired.enabled,
            "totalGB": desired.traffic_limit.bytes_limit or 0,
            "expiryTime": int(desired.expiry.expires_at.timestamp() * 1000)
            if desired.expiry.expires_at
            else 0,
            "limitIp": desired.device_or_ip_limit or 0,
            "subId": str(command.target_remote_identity),
        }
        try:
            inbound_ids = [int(value) for value in command.target_inbound_relationships]
            response = await self.transport.post_json(
                "/panel/api/clients/add",
                {"client": client, "inboundIds": inbound_ids},
            )
        except ValueError:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "NUMERIC_INBOUND_ID_REQUIRED"
            )
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
            return ProviderMutationResult(MutationOutcome.AMBIGUOUS, "PROVIDER_RESPONSE_LOST")
        except httpx.HTTPError:
            return ProviderMutationResult(MutationOutcome.AMBIGUOUS, "PROVIDER_TRANSPORT_FAILURE")
        if response.status_code == 429 or response.status_code >= 500:
            return ProviderMutationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_TEMPORARY_FAILURE"
            )
        if response.status_code in {401, 403}:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_FAILED"
            )
        if response.status_code in {409, 422}:
            try:
                reconciled = await self.reconcile(command)
            except (httpx.HTTPError, ProviderError):
                return ProviderMutationResult(
                    MutationOutcome.AMBIGUOUS, "CONFLICT_RECONCILIATION_UNAVAILABLE"
                )
            return reconciled or ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "PROVIDER_CONFLICT_NOT_RECONCILED"
            )
        if response.status_code >= 400:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "PROVIDER_REJECTED_CREATE"
            )
        body = response.json_body
        if not isinstance(body, Mapping):
            return ProviderMutationResult(
                MutationOutcome.CONTRACT_MISMATCH, "SUCCESS_ENVELOPE_INVALID"
            )
        envelope = cast(Mapping[str, object], body)
        if envelope.get("success") is not True:
            return ProviderMutationResult(
                MutationOutcome.CONTRACT_MISMATCH, "SUCCESS_ENVELOPE_INVALID"
            )
        try:
            verified = await self.reconcile(command)
        except (httpx.HTTPError, ProviderError):
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS, "POST_CREATE_RECONCILIATION_UNAVAILABLE"
            )
        return verified or ProviderMutationResult(
            MutationOutcome.AMBIGUOUS, "READ_AFTER_WRITE_NOT_VERIFIED"
        )


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
    """The only public production entry point; safety gates always precede HTTP."""
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
