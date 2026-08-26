"""Fail-closed production mutation execution for Sanaei/3x-ui v3.7.0.

The executor intentionally owns no HTTP retry loop.  Every ambiguous mutation is
followed by an authoritative global-client readback before a retry can be considered
safe by the durable worker.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import httpx
from vpnsale_domain.providers import (
    PanelInstance,
    ProviderCertificationStatus,
    ProviderError,
    ProviderErrorCode,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
)

from panel_adapters.sanaei_3x_ui_v370 import (
    SANAEI_3X_UI_V370_CONTRACT,
    Sanaei3xUiV370Client,
    Sanaei3xUiV370ClientRecord,
    Sanaei3xUiV370CreateRequest,
    sanaei_client_limit_fields,
)
from panel_adapters.write_execution import MutationOutcome, ProviderMutationResult


@dataclass(frozen=True)
class Sanaei3xUiV370Preflight:
    ready: bool
    outcome: MutationOutcome
    safe_code: str


def preflight_v370_mutation(
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> Sanaei3xUiV370Preflight:
    if not writes_enabled:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_WRITES_DISABLED"
        )
    if panel.provider_kind is not ProviderKind.SANAEI_3X_UI:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_EXECUTOR_UNSUPPORTED"
        )
    if panel.status.upper() not in {"ACTIVE", "ENABLED"}:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_PANEL_NOT_ACTIVE"
        )
    if certification_status is not ProviderCertificationStatus.CONTRACT_VERIFIED:
        return Sanaei3xUiV370Preflight(
            False,
            MutationOutcome.REQUIRES_RECERTIFICATION,
            "PROVIDER_RECERTIFICATION_REQUIRED",
        )
    contract = SANAEI_3X_UI_V370_CONTRACT
    if detected_version not in {contract.release_tag, contract.release_tag.lstrip("v")}:
        return Sanaei3xUiV370Preflight(
            False,
            MutationOutcome.REQUIRES_RECERTIFICATION,
            "PROVIDER_VERSION_NOT_CERTIFIED",
        )
    if detected_digest != contract.contract_digest:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.CONTRACT_MISMATCH, "PROVIDER_CONTRACT_MISMATCH"
        )
    if command.adapter_contract_version != contract.contract_digest:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.CONTRACT_MISMATCH, "COMMAND_CONTRACT_MISMATCH"
        )
    if command.expected_panel_version not in {
        contract.release_tag,
        contract.release_tag.lstrip("v"),
    }:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.CONTRACT_MISMATCH, "COMMAND_VERSION_MISMATCH"
        )
    if command.panel_reference != panel.public_reference:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.CONTRACT_MISMATCH, "COMMAND_PANEL_MISMATCH"
        )
    if command.operation not in {
        ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
        ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
        ProviderMutationOperation.ENABLE_REMOTE_IDENTITY,
        ProviderMutationOperation.DISABLE_REMOTE_IDENTITY,
    }:
        return Sanaei3xUiV370Preflight(
            False, MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_OPERATION_UNSUPPORTED"
        )
    return Sanaei3xUiV370Preflight(True, MutationOutcome.SUCCESS, "PROVIDER_PREFLIGHT_READY")


def _inbound_ids(command: ProviderMutationCommand) -> tuple[int, ...]:
    if not command.target_inbound_relationships:
        raise ValueError("authoritative inbound relationships are required")
    values: list[int] = []
    for item in command.target_inbound_relationships:
        value = int(str(item))
        if value <= 0:
            raise ValueError("authoritative inbound relationship is invalid")
        if value not in values:
            values.append(value)
    return tuple(values)


def _subscription_id(scope: str) -> str:
    # v3.7.0 requires a 16-character lower-case alphanumeric subscription id.
    return hashlib.sha256(scope.encode()).hexdigest()[:16]


def _client_payload(command: ProviderMutationCommand) -> dict[str, object]:
    desired = command.desired_state
    if command.target_remote_identity is None:
        raise ValueError("authoritative remote identity is required")
    limits = sanaei_client_limit_fields(
        total_bytes=desired.traffic_limit.bytes_limit or 0,
        expiry_at=desired.expiry.expires_at,
    )
    payload: dict[str, object] = {
        "id": str(command.target_remote_identity),
        "email": desired.provider_safe_label,
        "enable": desired.enabled,
        **limits,
        "limitIp": desired.device_or_ip_limit or 0,
        "tgId": 0,
        "subId": _subscription_id(command.idempotency_scope),
        "comment": desired.customer_safe_remark,
    }
    if desired.protocol == "vmess":
        payload["security"] = "auto"
    elif desired.protocol == "vless":
        payload["flow"] = ""
    return payload


def _matches(
    record: Sanaei3xUiV370ClientRecord,
    command: ProviderMutationCommand,
    inbound_ids: tuple[int, ...],
) -> bool:
    desired = command.desired_state
    if record.email != desired.provider_safe_label:
        return False
    remote_value = record.client.get("id", record.client.get("uuid"))
    if command.target_remote_identity is not None and remote_value is not None:
        if str(remote_value) != str(command.target_remote_identity):
            return False
    if not set(inbound_ids).issubset(record.inbound_ids):
        return False
    if record.client.get("enable") is not desired.enabled:
        return False
    if (
        not desired.traffic_limit.unlimited
        and record.client.get("totalGB") != desired.traffic_limit.bytes_limit
    ):
        return False
    if not desired.expiry.no_expiry:
        expected_expiry = sanaei_client_limit_fields(
            total_bytes=0,
            expiry_at=desired.expiry.expires_at,
        )["expiryTime"]
        if record.client.get("expiryTime") != expected_expiry:
            return False
    if (
        desired.device_or_ip_limit is not None
        and record.client.get("limitIp") != desired.device_or_ip_limit
    ):
        return False
    return True


def _safe_failure(exc: Exception, *, ambiguous: bool) -> ProviderMutationResult:
    if isinstance(exc, ProviderError):
        if exc.code in {
            ProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
            ProviderErrorCode.PROVIDER_AUTHORIZATION_INSUFFICIENT,
            ProviderErrorCode.PROVIDER_CREDENTIAL_UNAVAILABLE,
            ProviderErrorCode.PROVIDER_TLS_VERIFICATION_FAILED,
            ProviderErrorCode.PROVIDER_ENDPOINT_REJECTED,
        }:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_AUTH_OR_POLICY_BLOCKED"
            )
        if exc.code in {
            ProviderErrorCode.PROVIDER_TIMEOUT,
            ProviderErrorCode.PROVIDER_RATE_LIMITED,
            ProviderErrorCode.SERVICE_UNAVAILABLE,
        }:
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS if ambiguous else MutationOutcome.TRANSIENT_FAILURE,
                "PROVIDER_EXECUTION_UNAVAILABLE",
            )
        return ProviderMutationResult(
            MutationOutcome.AMBIGUOUS if ambiguous else MutationOutcome.CONTRACT_MISMATCH,
            "PROVIDER_RESPONSE_NOT_VERIFIED",
        )
    if isinstance(exc, TimeoutError | ConnectionError | OSError | httpx.HTTPError):
        return ProviderMutationResult(
            MutationOutcome.AMBIGUOUS if ambiguous else MutationOutcome.TRANSIENT_FAILURE,
            "PROVIDER_EXECUTION_UNAVAILABLE",
        )
    return ProviderMutationResult(
        MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_COMMAND_INVALID"
    )


class Sanaei3xUiV370Executor:
    def __init__(self, client: Sanaei3xUiV370Client) -> None:
        self.client = client

    async def _reconcile(
        self, command: ProviderMutationCommand, inbound_ids: tuple[int, ...]
    ) -> ProviderMutationResult | None:
        record = await self.client.read_client(command.desired_state.provider_safe_label)
        if not _matches(record, command, inbound_ids):
            return None
        return ProviderMutationResult(
            MutationOutcome.SUCCESS,
            "AUTHORITATIVE_RECONCILIATION_MATCH",
            command.target_remote_identity,
        )

    async def execute(self, command: ProviderMutationCommand) -> ProviderMutationResult:
        try:
            inbound_ids = _inbound_ids(command)
            payload = _client_payload(command)
        except (TypeError, ValueError):
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_COMMAND_INVALID"
            )

        if command.operation is ProviderMutationOperation.CREATE_REMOTE_IDENTITY:
            try:
                record = await self.client.add_client(
                    Sanaei3xUiV370CreateRequest(payload, inbound_ids)
                )
                if _matches(record, command, inbound_ids):
                    return ProviderMutationResult(
                        MutationOutcome.SUCCESS,
                        "CREATE_READ_AFTER_WRITE_VERIFIED",
                        command.target_remote_identity,
                    )
                return ProviderMutationResult(
                    MutationOutcome.AMBIGUOUS, "CREATE_POSTCONDITION_NOT_VERIFIED"
                )
            except Exception as exc:
                # A duplicate response or a lost response can still be a successful retry.
                try:
                    reconciled = await self._reconcile(command, inbound_ids)
                except Exception:
                    return _safe_failure(exc, ambiguous=True)
                return reconciled or _safe_failure(exc, ambiguous=False)

        try:
            current = await self.client.read_client(command.desired_state.provider_safe_label)
            missing = tuple(value for value in inbound_ids if value not in current.inbound_ids)
            if missing:
                current = await self.client.attach_client(current.email, missing)
            update_payload = dict(cast(Mapping[str, object], current.client))
            desired_payload = _client_payload(command)
            update_payload["enable"] = desired_payload["enable"]
            update_payload["comment"] = desired_payload["comment"]
            if not command.desired_state.traffic_limit.unlimited:
                update_payload["totalGB"] = desired_payload["totalGB"]
            if not command.desired_state.expiry.no_expiry:
                update_payload["expiryTime"] = desired_payload["expiryTime"]
            if command.desired_state.device_or_ip_limit is not None:
                update_payload["limitIp"] = desired_payload["limitIp"]
            record = await self.client.update_client(
                current.email,
                update_payload,
                inbound_ids=inbound_ids,
            )
            if not _matches(record, command, inbound_ids):
                return ProviderMutationResult(
                    MutationOutcome.AMBIGUOUS, "UPDATE_POSTCONDITION_NOT_VERIFIED"
                )
            return ProviderMutationResult(
                MutationOutcome.SUCCESS,
                "UPDATE_READ_AFTER_WRITE_VERIFIED",
                command.target_remote_identity,
            )
        except Exception as exc:
            try:
                reconciled = await self._reconcile(command, inbound_ids)
            except Exception:
                return _safe_failure(exc, ambiguous=True)
            return reconciled or _safe_failure(exc, ambiguous=False)


async def execute_v370_mutation(
    executor: Sanaei3xUiV370Executor,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> ProviderMutationResult:
    preflight = preflight_v370_mutation(
        panel,
        command,
        writes_enabled=writes_enabled,
        detected_version=detected_version,
        detected_digest=detected_digest,
        certification_status=certification_status,
    )
    if not preflight.ready:
        return ProviderMutationResult(preflight.outcome, preflight.safe_code)
    return await executor.execute(command)
