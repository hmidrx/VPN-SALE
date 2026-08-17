"""Certified additive Sanaei client adjustments for paid service operations.

The executor is deliberately narrower than the provider's general client update
surface.  It uses the exact 3x-ui v3.5.0 `/panel/api/clients/bulkAdjust`
contract to increase an existing client's traffic quota and/or expiry without
replacing unrelated client fields.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import cast

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
    RemoteClientSnapshot,
)

from panel_adapters.sanaei_3x_ui import Sanaei3xUiAdapter
from panel_adapters.write_contracts import preflight_mutation
from panel_adapters.write_execution import (
    MutationOutcome,
    ProviderMutationResult,
    SanaeiMutationTransport,
)

_SECONDS_PER_DAY = 24 * 60 * 60


def _same_millisecond(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if not hasattr(left, "timestamp") or not hasattr(right, "timestamp"):
        return False
    return int(left.timestamp() * 1000) == int(right.timestamp() * 1000)


class SanaeiAdjustExecutor:
    """Apply only additive quota/expiry deltas and verify authoritative state."""

    def __init__(self, transport: SanaeiMutationTransport, panel: PanelInstance) -> None:
        self.transport = transport
        self.panel = panel
        self.adapter = Sanaei3xUiAdapter()

    async def _matching_clients(
        self, command: ProviderMutationCommand
    ) -> tuple[RemoteClientSnapshot, ...]:
        inventory = await self.adapter.fetch_inventory(
            ProviderRequestContext(self.panel, correlation_id=command.correlation_reference),
            self.transport,
        )
        expected_identity = str(command.target_remote_identity or "")
        expected_label = command.desired_state.provider_safe_label
        return tuple(
            client
            for client in inventory.clients
            if str(client.remote_client_identity) == expected_identity
            or client.safe_remark == expected_label
        )

    @staticmethod
    def _canonical_client(
        matches: tuple[RemoteClientSnapshot, ...], command: ProviderMutationCommand
    ) -> RemoteClientSnapshot | None:
        if not matches:
            return None
        traffic_values = {client.traffic_limit_bytes for client in matches}
        expiry_values = {
            int(client.expiry_at.timestamp() * 1000) if client.expiry_at is not None else None
            for client in matches
        }
        inbound_values = {inbound for client in matches for inbound in client.inbound_remote_ids}
        expected_inbounds = set(command.target_inbound_relationships)
        if len(traffic_values) != 1 or len(expiry_values) != 1:
            return None
        if expected_inbounds and not expected_inbounds.issubset(inbound_values):
            return None
        return matches[0]

    @staticmethod
    def _target_reached(client: RemoteClientSnapshot, command: ProviderMutationCommand) -> bool:
        desired = command.desired_state
        traffic_target = desired.traffic_limit.bytes_limit
        expiry_target = desired.expiry.expires_at
        traffic_ok = (
            traffic_target is None
            or client.traffic_limit_bytes == traffic_target
        )
        expiry_ok = (
            expiry_target is None
            or _same_millisecond(client.expiry_at, expiry_target)
        )
        return traffic_ok and expiry_ok

    async def reconcile(self, command: ProviderMutationCommand) -> ProviderMutationResult | None:
        matches = await self._matching_clients(command)
        client = self._canonical_client(matches, command)
        if client is None or not self._target_reached(client, command):
            return None
        return ProviderMutationResult(
            MutationOutcome.SUCCESS,
            "AUTHORITATIVE_ADJUSTMENT_RECONCILIATION_MATCH",
            client.remote_client_identity,
        )

    async def _safe_reconcile(
        self, command: ProviderMutationCommand
    ) -> tuple[ProviderMutationResult | None, bool]:
        try:
            return await self.reconcile(command), True
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError, ProviderError):
            return None, False

    async def execute(self, command: ProviderMutationCommand) -> ProviderMutationResult:
        if command.operation is not ProviderMutationOperation.UPDATE_REMOTE_IDENTITY:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "OPERATION_UNSUPPORTED"
            )
        if command.target_remote_identity is None:
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "REMOTE_IDENTITY_REQUIRED"
            )
        if not command.desired_state.provider_safe_label.strip():
            return ProviderMutationResult(
                MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_LABEL_REQUIRED"
            )

        matches = await self._matching_clients(command)
        current = self._canonical_client(matches, command)
        if current is None:
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS, "AUTHORITATIVE_CURRENT_STATE_UNAVAILABLE"
            )
        if self._target_reached(current, command):
            return ProviderMutationResult(
                MutationOutcome.SUCCESS,
                "AUTHORITATIVE_ADJUSTMENT_RECONCILIATION_MATCH",
                current.remote_client_identity,
            )

        desired = command.desired_state
        add_bytes = 0
        traffic_target = desired.traffic_limit.bytes_limit
        if traffic_target is not None:
            if current.traffic_limit_bytes is None:
                return ProviderMutationResult(
                    MutationOutcome.BLOCKED_BY_CONFIGURATION,
                    "FINITE_TRAFFIC_BASELINE_REQUIRED",
                )
            add_bytes = traffic_target - current.traffic_limit_bytes
            if add_bytes < 0:
                return ProviderMutationResult(
                    MutationOutcome.BLOCKED_BY_CONFIGURATION,
                    "DESTRUCTIVE_TRAFFIC_ADJUSTMENT_BLOCKED",
                )

        add_days = 0
        expiry_target = desired.expiry.expires_at
        if expiry_target is not None:
            if current.expiry_at is None:
                return ProviderMutationResult(
                    MutationOutcome.BLOCKED_BY_CONFIGURATION,
                    "FINITE_EXPIRY_BASELINE_REQUIRED",
                )
            delta = expiry_target - current.expiry_at
            seconds = int(delta.total_seconds())
            if delta <= timedelta(0):
                return ProviderMutationResult(
                    MutationOutcome.BLOCKED_BY_CONFIGURATION,
                    "DESTRUCTIVE_EXPIRY_ADJUSTMENT_BLOCKED",
                )
            if delta.microseconds != 0 or seconds % _SECONDS_PER_DAY != 0:
                return ProviderMutationResult(
                    MutationOutcome.CONTRACT_MISMATCH,
                    "EXPIRY_ADJUSTMENT_MUST_BE_WHOLE_DAYS",
                )
            add_days = seconds // _SECONDS_PER_DAY

        if add_bytes == 0 and add_days == 0:
            return ProviderMutationResult(
                MutationOutcome.CONTRACT_MISMATCH,
                "NO_SUPPORTED_ADJUSTMENT",
            )

        payload: Mapping[str, object] = {
            "emails": [desired.provider_safe_label],
            "addDays": add_days,
            "addBytes": add_bytes,
            "flow": "",
        }
        try:
            response = await self.transport.post_json(
                "/panel/api/clients/bulkAdjust", payload
            )
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError):
            reconciled, available = await self._safe_reconcile(command)
            if reconciled is not None:
                return reconciled
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS if available else MutationOutcome.TRANSIENT_FAILURE,
                "PROVIDER_RESPONSE_LOST"
                if available
                else "PROVIDER_RECONCILIATION_UNAVAILABLE",
            )

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
            response.status_code < 400
            and envelope is not None
            and envelope.get("success") is True
        )
        verified, available = await self._safe_reconcile(command)
        if verified is not None:
            return verified
        if not available:
            return ProviderMutationResult(
                MutationOutcome.AMBIGUOUS, "POST_ADJUST_RECONCILIATION_UNAVAILABLE"
            )
        if not accepted:
            return ProviderMutationResult(
                MutationOutcome.PERMANENT_FAILURE, "PROVIDER_REJECTED_ADJUSTMENT"
            )
        return ProviderMutationResult(
            MutationOutcome.AMBIGUOUS, "READ_AFTER_WRITE_NOT_VERIFIED"
        )


async def execute_certified_sanaei_adjust(
    executor: SanaeiAdjustExecutor,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    *,
    writes_enabled: bool,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
) -> ProviderMutationResult:
    """Safety-gated production entry point for existing-client adjustments."""
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
            MutationOutcome.REQUIRES_RECERTIFICATION,
            "PROVIDER_RECERTIFICATION_REQUIRED",
        )
    if preflight.status is MutationPreflightStatus.CONTRACT_MISMATCH:
        return ProviderMutationResult(
            MutationOutcome.CONTRACT_MISMATCH, "CONTRACT_MISMATCH"
        )
    if preflight.status is not MutationPreflightStatus.READY:
        return ProviderMutationResult(
            MutationOutcome.BLOCKED_BY_CONFIGURATION, "PROVIDER_PREFLIGHT_BLOCKED"
        )
    return await executor.execute(command)
