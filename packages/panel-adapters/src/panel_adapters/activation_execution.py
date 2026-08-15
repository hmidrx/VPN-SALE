"""Certified Sanaei 3x-ui v3.5.0 activation with read-before/reconcile semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from vpnsale_domain.providers import (
    MutationPreflightStatus,
    PanelInstance,
    ProviderCertificationStatus,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteIdentifier,
)

from panel_adapters.write_contracts import preflight_mutation
from panel_adapters.write_execution import MutationOutcome, SanaeiMutationTransport


@dataclass(frozen=True)
class ProviderActivationResult:
    outcome: MutationOutcome
    safe_code: str
    remote_identity: RemoteIdentifier | None = None


class SanaeiActivationExecutor:
    """Activate one already-provisioned client through the exact v3.5.0 global client API."""

    def __init__(self, transport: SanaeiMutationTransport, panel: PanelInstance) -> None:
        self.transport = transport
        self.panel = panel

    @staticmethod
    def _path_label(command: ProviderMutationCommand) -> str:
        return command.desired_state.provider_safe_label

    async def _read_client(self, command: ProviderMutationCommand) -> Mapping[str, object] | None:
        path = f"/panel/api/clients/get/{quote(self._path_label(command), safe='')}"
        response = await self.transport.get(path)
        if response.status_code in {401, 403}:
            raise PermissionError("provider authentication failed")
        if response.status_code == 429 or response.status_code >= 500:
            raise ConnectionError("provider read unavailable")
        if response.status_code >= 400:
            return None
        body = response.json_body
        if not isinstance(body, Mapping):
            raise ValueError("provider client envelope invalid")
        if body.get("success") is not True:
            return None
        obj = body.get("obj")
        if not isinstance(obj, Mapping):
            raise ValueError("provider client object invalid")
        client = obj.get("client")
        if not isinstance(client, Mapping):
            raise ValueError("provider client record invalid")
        return client

    async def _safe_read(
        self, command: ProviderMutationCommand
    ) -> tuple[Mapping[str, object] | None, str | None]:
        try:
            return await self._read_client(command), None
        except PermissionError:
            return None, "AUTH"
        except (
            TimeoutError,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.HTTPError,
            ConnectionError,
        ):
            return None, "TRANSIENT"
        except ValueError:
            return None, "CONTRACT"

    @staticmethod
    def _desired_values(command: ProviderMutationCommand) -> tuple[str, int, int, int]:
        desired = command.desired_state
        if command.target_remote_identity is None or not desired.enabled:
            raise ValueError("activation requires an enabled target identity")
        if desired.traffic_limit.bytes_limit is None or desired.traffic_limit.unlimited:
            raise ValueError("activation requires an explicit traffic limit")
        if desired.expiry.expires_at is None or desired.expiry.no_expiry:
            raise ValueError("activation requires an explicit expiry")
        if desired.device_or_ip_limit is None or desired.device_or_ip_limit <= 0:
            raise ValueError("activation requires an explicit device limit")
        return (
            str(command.target_remote_identity),
            desired.traffic_limit.bytes_limit,
            int(desired.expiry.expires_at.timestamp() * 1000),
            desired.device_or_ip_limit,
        )

    @classmethod
    def _matches(cls, client: Mapping[str, object], command: ProviderMutationCommand) -> bool:
        remote_id, traffic, expiry_ms, device_limit = cls._desired_values(command)
        return (
            str(client.get("id") or "") == remote_id
            and str(client.get("email") or "") == cls._path_label(command)
            and client.get("enable") is True
            and type(client.get("totalGB")) is int
            and int(client["totalGB"]) == traffic
            and type(client.get("expiryTime")) is int
            and int(client["expiryTime"]) == expiry_ms
            and type(client.get("limitIp")) is int
            and int(client["limitIp"]) == device_limit
        )

    async def execute(self, command: ProviderMutationCommand) -> ProviderActivationResult:
        if command.operation is not ProviderMutationOperation.UPDATE_REMOTE_IDENTITY:
            return ProviderActivationResult(
                MutationOutcome.PERMANENT_FAILURE, "OPERATION_UNSUPPORTED"
            )
        try:
            remote_id, traffic, expiry_ms, device_limit = self._desired_values(command)
        except ValueError:
            return ProviderActivationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION,
                "ACTIVATION_DESIRED_STATE_INVALID",
            )

        current, read_error = await self._safe_read(command)
        if read_error == "AUTH":
            return ProviderActivationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_FAILED"
            )
        if read_error == "TRANSIENT":
            return ProviderActivationResult(
                MutationOutcome.TRANSIENT_FAILURE,
                "PROVIDER_RECONCILIATION_UNAVAILABLE",
            )
        if read_error == "CONTRACT":
            return ProviderActivationResult(
                MutationOutcome.CONTRACT_MISMATCH, "CLIENT_READ_CONTRACT_MISMATCH"
            )
        if current is None:
            return ProviderActivationResult(
                MutationOutcome.PERMANENT_FAILURE, "REMOTE_IDENTITY_MISSING"
            )
        if str(current.get("id") or "") != remote_id:
            return ProviderActivationResult(
                MutationOutcome.PERMANENT_FAILURE, "REMOTE_IDENTITY_MISMATCH"
            )
        if self._matches(current, command):
            return ProviderActivationResult(
                MutationOutcome.SUCCESS,
                "AUTHORITATIVE_ACTIVATION_MATCH",
                RemoteIdentifier(remote_id),
            )

        payload = dict(current)
        payload.update(
            {
                "id": remote_id,
                "email": self._path_label(command),
                "enable": True,
                "totalGB": traffic,
                "expiryTime": expiry_ms,
                "limitIp": device_limit,
            }
        )
        path = f"/panel/api/clients/update/{quote(self._path_label(command), safe='')}"
        try:
            response = await self.transport.post_json(path, payload)
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            return ProviderActivationResult(MutationOutcome.AMBIGUOUS, "PROVIDER_RESPONSE_LOST")

        if response.status_code in {401, 403}:
            return ProviderActivationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_FAILED"
            )
        if response.status_code == 429 or response.status_code >= 500:
            return ProviderActivationResult(
                MutationOutcome.TRANSIENT_FAILURE, "PROVIDER_TEMPORARY_FAILURE"
            )
        envelope = response.json_body if isinstance(response.json_body, Mapping) else None
        accepted = (
            response.status_code < 400 and envelope is not None and envelope.get("success") is True
        )

        verified, verify_error = await self._safe_read(command)
        if verify_error == "AUTH":
            return ProviderActivationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_FAILED"
            )
        if verify_error == "TRANSIENT":
            return ProviderActivationResult(
                MutationOutcome.AMBIGUOUS,
                "POST_ACTIVATION_RECONCILIATION_UNAVAILABLE",
            )
        if verify_error == "CONTRACT":
            return ProviderActivationResult(
                MutationOutcome.CONTRACT_MISMATCH, "CLIENT_READ_CONTRACT_MISMATCH"
            )
        if verified is None or not self._matches(verified, command):
            if not accepted:
                return ProviderActivationResult(
                    MutationOutcome.PERMANENT_FAILURE, "PROVIDER_REJECTED_ACTIVATION"
                )
            return ProviderActivationResult(
                MutationOutcome.AMBIGUOUS, "ACTIVATION_POSTCONDITION_NOT_VERIFIED"
            )
        return ProviderActivationResult(
            MutationOutcome.SUCCESS,
            "ACTIVATION_VERIFIED",
            RemoteIdentifier(remote_id),
        )


async def execute_certified_sanaei_activation(
    executor: SanaeiActivationExecutor,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> ProviderActivationResult:
    """Fail-closed public entry point; provider mutation happens only after all safety gates."""
    if not writes_enabled:
        return ProviderActivationResult(
            MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_WRITES_DISABLED"
        )
    if panel.provider_kind is not ProviderKind.SANAEI_3X_UI:
        return ProviderActivationResult(
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
        return ProviderActivationResult(
            MutationOutcome.REQUIRES_RECERTIFICATION,
            "PROVIDER_RECERTIFICATION_REQUIRED",
        )
    if preflight.status is MutationPreflightStatus.CONTRACT_MISMATCH:
        return ProviderActivationResult(MutationOutcome.CONTRACT_MISMATCH, "CONTRACT_MISMATCH")
    if preflight.status is not MutationPreflightStatus.READY:
        return ProviderActivationResult(
            MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_PREFLIGHT_BLOCKED"
        )
    return await executor.execute(command)
