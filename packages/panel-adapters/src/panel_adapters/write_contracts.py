"""Milestone 6-A2A provider write-contract safety gate.

This module contains provider-specific upstream write DTO names and sanitized dry-run
planning only. It never performs a provider mutation and never exposes raw payloads.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from vpnsale_domain.providers import (
    CapabilitySupport,
    DesiredRemoteIdentity,
    DryRunMutationPlan,
    MutationPreflightResult,
    MutationPreflightStatus,
    PanelInstance,
    ProviderCapability,
    ProviderCapabilityEvidence,
    ProviderCertificationStatus,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    ProviderWriteState,
)

from panel_adapters.contracts import CERTIFIED_CONTRACTS, canonical_digest


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


@dataclass(frozen=True)
class UpstreamWriteOperationContract:
    operation: ProviderMutationOperation
    endpoint_identifier: str
    method: HttpMethod
    authentication: str
    content_type: str
    request_dto: str
    response_dto: str
    success_conditions: tuple[str, ...]
    error_conditions: tuple[str, ...]
    side_effects: tuple[str, ...]
    atomic: bool
    naturally_idempotent: bool
    read_after_write: str
    compensation: str
    sensitive_fields: tuple[str, ...]
    capability: ProviderCapability
    evidence: str
    support: CapabilitySupport = CapabilitySupport.SUPPORTED


@dataclass(frozen=True)
class ProviderWriteContract:
    provider: ProviderKind
    target_tag: str
    target_commit: str
    digest: str
    write_state: ProviderWriteState
    operations: tuple[UpstreamWriteOperationContract, ...]
    unsupported: tuple[ProviderMutationOperation, ...]
    correction_warning: str | None = None


def _op(
    operation: ProviderMutationOperation,
    endpoint: str,
    method: HttpMethod,
    auth: str,
    request_dto: str,
    response_dto: str,
    capability: ProviderCapability,
    evidence: str,
    *,
    atomic: bool = False,
    idempotent: bool = False,
    side_effects: tuple[str, ...] = (),
) -> UpstreamWriteOperationContract:
    return UpstreamWriteOperationContract(
        operation=operation,
        endpoint_identifier=endpoint,
        method=method,
        authentication=auth,
        content_type="application/json",
        request_dto=request_dto,
        response_dto=response_dto,
        success_conditions=("runtime_validated_success_envelope", "postconditions_verified"),
        error_conditions=("401", "403", "404", "409", "422", "429", "5xx", "timeout"),
        side_effects=side_effects or ("remote_panel_state_changes_if_future_execution_enabled",),
        atomic=atomic,
        naturally_idempotent=idempotent,
        read_after_write="authoritative inventory/read endpoint before declaring success",
        compensation="reconcile first; never blindly retry ambiguous or non-idempotent mutation",
        sensitive_fields=("credential", "uuid", "password", "token", "cookie", "raw_payload"),
        capability=capability,
        evidence=evidence,
    )


def provider_write_contracts() -> dict[ProviderKind, ProviderWriteContract]:
    sanaei = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
    alireza = CERTIFIED_CONTRACTS[ProviderKind.ALIREZA_X_UI]
    pasar = CERTIFIED_CONTRACTS[ProviderKind.PASARGUARD]
    sanaei_ops = (
        _op(
            ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
            "sanaei.clients.add",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientCreateRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_CREATE,
            "internal/web/controller/api.go and client.go@v3.5.0; JSON ClientCreatePayload",
        ),
        _op(
            ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
            "sanaei.clients.update",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientUpdateRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_UPDATE,
            "v3.5.0 client service update DTO",
            side_effects=("hot applies xray client settings where controller service succeeds",),
        ),
        _op(
            ProviderMutationOperation.ENABLE_REMOTE_IDENTITY,
            "sanaei.clients.enable",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientEnableRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_ENABLE,
            "v3.5.0 client enable field in update DTO",
        ),
        _op(
            ProviderMutationOperation.DISABLE_REMOTE_IDENTITY,
            "sanaei.clients.disable",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientEnableRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_DISABLE,
            "v3.5.0 client enable field in update DTO",
        ),
        _op(
            ProviderMutationOperation.DELETE_REMOTE_IDENTITY,
            "sanaei.clients.delete",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientDeleteRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_DELETE,
            "v3.5.0 client delete route",
        ),
        _op(
            ProviderMutationOperation.RESET_REMOTE_TRAFFIC,
            "sanaei.clients.resetTraffic",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientTrafficResetRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_TRAFFIC_RESET,
            "v3.5.0 traffic reset controller",
        ),
        _op(
            ProviderMutationOperation.CLEAR_REMOTE_CLIENT_IPS,
            "sanaei.clients.clearIps",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiClientIpClearRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.CLIENT_IP_CLEAR,
            "v3.5.0 clear client IP route",
        ),
        _op(
            ProviderMutationOperation.ATTACH_REMOTE_INBOUND,
            "sanaei.clients.attachInbound",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiInboundAttachmentRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.MULTI_INBOUND_ASSIGNMENT,
            "v3.5.0 multi-inbound client relationship service",
        ),
        _op(
            ProviderMutationOperation.DETACH_REMOTE_INBOUND,
            "sanaei.clients.detachInbound",
            HttpMethod.POST,
            "session_cookie",
            "SanaeiInboundAttachmentRequest",
            "SanaeiSuccessEnvelope",
            ProviderCapability.MULTI_INBOUND_ASSIGNMENT,
            "v3.5.0 multi-inbound client relationship service",
        ),
    )
    alireza_ops = (
        _op(
            ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
            "alireza.inbounds.addClient",
            HttpMethod.POST,
            "session_cookie",
            "AlirezaAddClientEnvelope",
            "AlirezaSuccessEnvelope",
            ProviderCapability.CLIENT_CREATE,
            "web/controller/api.go@v1.11.3 /xui/API/inbounds/addClient/",
        ),
        _op(
            ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
            "alireza.inbounds.updateClient",
            HttpMethod.POST,
            "session_cookie",
            "AlirezaUpdateClientEnvelope",
            "AlirezaSuccessEnvelope",
            ProviderCapability.CLIENT_UPDATE,
            "web/controller/api.go@v1.11.3 /xui/API/inbounds/updateClient/:clientId",
        ),
        _op(
            ProviderMutationOperation.DELETE_REMOTE_IDENTITY,
            "alireza.inbounds.delClient",
            HttpMethod.POST,
            "session_cookie",
            "AlirezaDeleteClientPath",
            "AlirezaSuccessEnvelope",
            ProviderCapability.CLIENT_DELETE,
            "web/controller/api.go@v1.11.3 /xui/API/inbounds/:id/delClient/:clientId",
        ),
        _op(
            ProviderMutationOperation.RESET_REMOTE_TRAFFIC,
            "alireza.inbounds.resetClientTraffic",
            HttpMethod.POST,
            "session_cookie",
            "AlirezaResetTrafficPath",
            "AlirezaSuccessEnvelope",
            ProviderCapability.CLIENT_TRAFFIC_RESET,
            "web/controller/api.go@v1.11.3 /xui/API/inbounds/:id/resetClientTraffic/:email",
        ),
        _op(
            ProviderMutationOperation.ENABLE_REMOTE_IDENTITY,
            "alireza.inbounds.updateClient.enable",
            HttpMethod.POST,
            "session_cookie",
            "AlirezaFullClientReplacementEnvelope",
            "AlirezaSuccessEnvelope",
            ProviderCapability.CLIENT_ENABLE,
            "enable/disable requires preserving full nested client object",
        ),
        _op(
            ProviderMutationOperation.DISABLE_REMOTE_IDENTITY,
            "alireza.inbounds.updateClient.disable",
            HttpMethod.POST,
            "session_cookie",
            "AlirezaFullClientReplacementEnvelope",
            "AlirezaSuccessEnvelope",
            ProviderCapability.CLIENT_DISABLE,
            "enable/disable requires preserving full nested client object",
        ),
    )
    pasar_ops = (
        _op(
            ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
            "pasarguard.users.create",
            HttpMethod.POST,
            "admin_session_cookie",
            "PasarGuardUserCreateRequest",
            "PasarGuardUserEnvelope",
            ProviderCapability.CLIENT_CREATE,
            (
                "PasarGuard/panel v4.0.2 user route source; panel auth is "
                "administrator session, not node API key"
            ),
        ),
        _op(
            ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
            "pasarguard.users.update",
            HttpMethod.PATCH,
            "admin_session_cookie",
            "PasarGuardUserUpdateRequest",
            "PasarGuardUserEnvelope",
            ProviderCapability.CLIENT_UPDATE,
            "PasarGuard/panel v4.0.2 ID-based user modification route",
        ),
        _op(
            ProviderMutationOperation.ENABLE_REMOTE_IDENTITY,
            "pasarguard.users.enable",
            HttpMethod.PATCH,
            "admin_session_cookie",
            "PasarGuardUserStatusRequest",
            "PasarGuardUserEnvelope",
            ProviderCapability.CLIENT_ENABLE,
            "PasarGuard/panel v4.0.2 user status field",
        ),
        _op(
            ProviderMutationOperation.DISABLE_REMOTE_IDENTITY,
            "pasarguard.users.disable",
            HttpMethod.PATCH,
            "admin_session_cookie",
            "PasarGuardUserStatusRequest",
            "PasarGuardUserEnvelope",
            ProviderCapability.CLIENT_DISABLE,
            "PasarGuard/panel v4.0.2 user status field",
        ),
        _op(
            ProviderMutationOperation.DELETE_REMOTE_IDENTITY,
            "pasarguard.users.delete",
            HttpMethod.DELETE,
            "admin_session_cookie",
            "PasarGuardUserIdPath",
            "PasarGuardDeleteEnvelope",
            ProviderCapability.CLIENT_DELETE,
            "PasarGuard/panel v4.0.2 ID-based user deletion route",
            side_effects=(
                (
                    "panel user deleted; node sync side effects are provider-managed "
                    "and eventually consistent"
                ),
            ),
        ),
        _op(
            ProviderMutationOperation.RESET_REMOTE_TRAFFIC,
            "pasarguard.users.resetTraffic",
            HttpMethod.POST,
            "admin_session_cookie",
            "PasarGuardUserResetTrafficRequest",
            "PasarGuardUserEnvelope",
            ProviderCapability.CLIENT_TRAFFIC_RESET,
            "PasarGuard/panel v4.0.2 user traffic reset route",
        ),
    )
    return {
        ProviderKind.SANAEI_3X_UI: ProviderWriteContract(
            ProviderKind.SANAEI_3X_UI,
            sanaei.release_tag,
            sanaei.commit_sha,
            canonical_digest([o.endpoint_identifier for o in sanaei_ops]),
            ProviderWriteState.LIVE_WRITE_CANARY_REQUIRED,
            sanaei_ops,
            (ProviderMutationOperation.REVOKE_REMOTE_SUBSCRIPTION_IDENTITY,),
        ),
        ProviderKind.ALIREZA_X_UI: ProviderWriteContract(
            ProviderKind.ALIREZA_X_UI,
            alireza.release_tag,
            alireza.commit_sha,
            canonical_digest([o.endpoint_identifier for o in alireza_ops]),
            ProviderWriteState.LIVE_WRITE_CANARY_REQUIRED,
            alireza_ops,
            (
                ProviderMutationOperation.ATTACH_REMOTE_INBOUND,
                ProviderMutationOperation.DETACH_REMOTE_INBOUND,
                ProviderMutationOperation.CLEAR_REMOTE_CLIENT_IPS,
                ProviderMutationOperation.REVOKE_REMOTE_SUBSCRIPTION_IDENTITY,
            ),
        ),
        ProviderKind.PASARGUARD: ProviderWriteContract(
            ProviderKind.PASARGUARD,
            pasar.release_tag,
            pasar.commit_sha,
            canonical_digest([o.endpoint_identifier for o in pasar_ops]),
            ProviderWriteState.LIVE_WRITE_CANARY_REQUIRED,
            pasar_ops,
            (
                ProviderMutationOperation.ATTACH_REMOTE_INBOUND,
                ProviderMutationOperation.DETACH_REMOTE_INBOUND,
                ProviderMutationOperation.CLEAR_REMOTE_CLIENT_IPS,
                ProviderMutationOperation.ROTATE_REMOTE_CREDENTIAL,
                ProviderMutationOperation.REVOKE_REMOTE_SUBSCRIPTION_IDENTITY,
            ),
            (
                "Milestone 6-A1 PasarGuard v5.1.0/API-key/OpenAPI assumptions "
                "are invalidated; v4.0.2 requires re-certification."
            ),
        ),
    }


_OPERATION_CAPABILITIES = {
    ProviderMutationOperation.CREATE_REMOTE_IDENTITY: ProviderCapability.CLIENT_CREATE,
    ProviderMutationOperation.UPDATE_REMOTE_IDENTITY: ProviderCapability.CLIENT_UPDATE,
    ProviderMutationOperation.ENABLE_REMOTE_IDENTITY: ProviderCapability.CLIENT_ENABLE,
    ProviderMutationOperation.DISABLE_REMOTE_IDENTITY: ProviderCapability.CLIENT_DISABLE,
    ProviderMutationOperation.DELETE_REMOTE_IDENTITY: ProviderCapability.CLIENT_DELETE,
    ProviderMutationOperation.RESET_REMOTE_TRAFFIC: ProviderCapability.CLIENT_TRAFFIC_RESET,
    ProviderMutationOperation.CLEAR_REMOTE_CLIENT_IPS: ProviderCapability.CLIENT_IP_CLEAR,
    ProviderMutationOperation.SET_REMOTE_TRAFFIC_LIMIT: (
        ProviderCapability.CLIENT_TRAFFIC_LIMIT_UPDATE
    ),
    ProviderMutationOperation.SET_REMOTE_EXPIRY: ProviderCapability.CLIENT_EXPIRY_UPDATE,
    ProviderMutationOperation.SET_REMOTE_DEVICE_OR_IP_LIMIT: (
        ProviderCapability.CLIENT_DEVICE_LIMIT_UPDATE
    ),
    ProviderMutationOperation.ATTACH_REMOTE_INBOUND: ProviderCapability.MULTI_INBOUND_ASSIGNMENT,
    ProviderMutationOperation.DETACH_REMOTE_INBOUND: ProviderCapability.MULTI_INBOUND_ASSIGNMENT,
    ProviderMutationOperation.REVOKE_REMOTE_SUBSCRIPTION_IDENTITY: (
        ProviderCapability.CLIENT_REVOKE_SUBSCRIPTION
    ),
}


def preflight_mutation(
    panel: PanelInstance,
    provider: ProviderKind,
    command: ProviderMutationCommand,
    detected_version: str | None,
    detected_digest: str | None,
    certification_status: ProviderCertificationStatus,
    active_operation_keys: frozenset[str] = frozenset(),
) -> MutationPreflightResult:
    contract = provider_write_contracts()[provider]
    reasons: list[str] = []
    capability = _OPERATION_CAPABILITIES.get(command.operation)
    if panel.status != "enabled":
        reasons.append("panel_not_enabled")
    if panel.credential_reference is None or not panel.credential_reference.configured:
        reasons.append("credential_unavailable")
    if detected_version not in {contract.target_tag, contract.target_tag.lstrip("v")}:
        return MutationPreflightResult(
            MutationPreflightStatus.REQUIRES_RECERTIFICATION,
            command.operation,
            capability,
            ("exact_version_not_certified",),
        )
    if detected_digest and detected_digest != CERTIFIED_CONTRACTS[provider].contract_digest:
        return MutationPreflightResult(
            MutationPreflightStatus.CONTRACT_MISMATCH,
            command.operation,
            capability,
            ("contract_digest_mismatch",),
        )
    if certification_status != ProviderCertificationStatus.CONTRACT_VERIFIED:
        return MutationPreflightResult(
            MutationPreflightStatus.REQUIRES_RECERTIFICATION,
            command.operation,
            capability,
            ("read_certification_required",),
        )
    if command.operation in contract.unsupported:
        return MutationPreflightResult(
            MutationPreflightStatus.UNSUPPORTED,
            command.operation,
            capability,
            ("operation_unsupported_by_verified_contract",),
        )
    if command.idempotency_scope in active_operation_keys:
        return MutationPreflightResult(
            MutationPreflightStatus.BLOCKED,
            command.operation,
            capability,
            ("conflicting_operation_active",),
        )
    if (
        not command.expected_remote_snapshot
        and command.operation is not ProviderMutationOperation.CREATE_REMOTE_IDENTITY
    ):
        return MutationPreflightResult(
            MutationPreflightStatus.STALE_REMOTE_STATE,
            command.operation,
            capability,
            ("expected_remote_snapshot_required",),
        )
    if reasons:
        return MutationPreflightResult(
            MutationPreflightStatus.BLOCKED, command.operation, capability, tuple(reasons)
        )
    return MutationPreflightResult(
        MutationPreflightStatus.READY,
        command.operation,
        capability,
        ("all_write_safety_gates_passed_without_transport",),
    )


def build_dry_run_plan(
    provider: ProviderKind,
    panel: PanelInstance,
    command: ProviderMutationCommand,
    current_state: DesiredRemoteIdentity | None = None,
) -> DryRunMutationPlan:
    contract = provider_write_contracts()[provider]
    operation = next(
        (item for item in contract.operations if item.operation is command.operation), None
    )
    if operation is None:
        raise ValueError("unsupported operation cannot produce a dry-run plan")
    current = current_state or command.desired_state
    changed = tuple(
        field
        for field in (
            "enabled",
            "traffic_limit",
            "expiry",
            "device_or_ip_limit",
            "inbound_assignments",
            "provider_safe_label",
        )
        if getattr(current, field) != getattr(command.desired_state, field)
    ) or (command.operation.value,)
    evidence = (
        ProviderCapabilityEvidence(
            operation.capability,
            CapabilitySupport.SUPPORTED,
            command.adapter_contract_version,
            operation.evidence,
        ),
    )
    warnings = (contract.correction_warning,) if contract.correction_warning else ()
    expires_at = datetime.now(UTC) + timedelta(minutes=15)
    digest_source = {
        "provider": provider.value,
        "operation": command.operation.value,
        "panel": command.panel_reference,
        "identity": command.target_remote_identity,
        "inbounds": command.target_inbound_relationships,
        "changed": changed,
        "endpoint": operation.endpoint_identifier,
        "expires_at": expires_at.isoformat(),
    }
    plan_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(digest_source, sort_keys=True, default=str).encode()
        ).hexdigest()
    )
    return DryRunMutationPlan(
        provider,
        command.adapter_contract_version,
        command.operation,
        panel.public_reference,
        command.target_remote_identity,
        command.target_inbound_relationships,
        changed,
        evidence,
        operation.endpoint_identifier,
        operation.response_dto,
        ("authoritative remote read confirms desired state", "HTTP success alone is insufficient"),
        (operation.read_after_write, "compare snapshot before retry after timeout"),
        operation.compensation,
        "read-before-retry-for-ambiguous-timeouts",
        "high-until-live-canary",
        warnings,
        expires_at,
        plan_digest,
    )


def execute_provider_mutation_disabled() -> str:
    return "PROVIDER_WRITE_NOT_ENABLED"
