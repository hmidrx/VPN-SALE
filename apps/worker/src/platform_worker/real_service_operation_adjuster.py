"""Database-bound composition for certified Sanaei service-operation adjustments."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import cast
from uuid import UUID

from panel_adapters.contracts import CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.sanaei_adjust_execution import (
    SanaeiAdjustExecutor,
    execute_certified_sanaei_adjust,
)
from panel_adapters.write_execution import MutationOutcome, SanaeiAuthenticatedTransport
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    ProviderCertificationStatus,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceModel,
    ServiceOperationAttachmentPlanModel,
    ServiceOperationModel,
)
from platform_worker.real_activator import DatabaseSanaeiActivator
from platform_worker.service_operation_execution import AdjustmentResult


class DatabaseSanaeiServiceOperationAdjuster(DatabaseSanaeiActivator):
    """Reuse the certified panel/credential selection path and execute additive changes."""

    def adjust(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> AdjustmentResult:
        if not self.writes_enabled:
            return AdjustmentResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")
        try:
            panel, target, certification, username, password = self._select(attachment)
            remote_identity = self._remote_identity(attachment)
            target_state_value = plan.result_snapshot.get("target_state")
            if not isinstance(target_state_value, dict):
                raise ValueError("service operation target unavailable")
            target_state = cast(dict[str, object], target_state_value)
            base_url = EndpointValidator().validate(
                panel.endpoint_origin + panel.base_path,
                panel.endpoint_policy,
                panel.tls_policy,
            )
            contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
            inbound = RemoteIdentifier(target.inbound_id)
            provider_label = f"svc-{remote_identity.replace('-', '')[:20]}"
            device_limit_value = service.entitlement_snapshot.get("device_limit")
            device_limit = (
                device_limit_value
                if type(device_limit_value) is int and device_limit_value > 0
                else None
            )
            kind = target_state.get("kind")
            if kind == "RENEW":
                expiry_raw = target_state.get("target_expiry")
                if not isinstance(expiry_raw, str):
                    raise ValueError("renew target expiry invalid")
                expiry = datetime.fromisoformat(expiry_raw)
                if expiry.tzinfo is None:
                    raise ValueError("renew target expiry must be timezone aware")
                traffic = RemoteTrafficLimit(None, unlimited=True)
                expiry_policy = RemoteExpiryPolicy(expiry)
            elif kind == "ADD_TRAFFIC":
                traffic_raw = target_state.get("target_traffic_quota_bytes")
                if type(traffic_raw) is not int or traffic_raw <= 0:
                    raise ValueError("traffic target invalid")
                traffic = RemoteTrafficLimit(traffic_raw)
                expiry_policy = RemoteExpiryPolicy(None, no_expiry=True)
            else:
                raise ValueError("service operation target kind unsupported")
            command = ProviderMutationCommand(
                UUID(operation.id),
                ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
                service.public_reference,
                f"customer_{service.beneficiary_customer_id[:12]}",
                panel.public_reference,
                contract.contract_digest,
                certification.detected_version or "",
                RemoteIdentifier(remote_identity),
                (inbound,),
                DesiredRemoteIdentity(
                    service.public_reference,
                    target.required_protocol,
                    True,
                    traffic,
                    expiry_policy,
                    device_limit,
                    "customer service",
                    provider_label,
                    (inbound,),
                ),
                plan.expected_snapshot_digest,
                f"service-operation:v1:{operation.id}:{attachment.id}",
                "service-operation-worker",
                "execute paid service operation",
                operation.updated_at,
                f"service-operation:{operation.id}",
                operation.id,
            )
        except (KeyError, TypeError, ValueError):
            return AdjustmentResult(
                "BLOCKED_BY_CONFIGURATION", "SERVICE_OPERATION_SELECTION_BLOCKED"
            )
        return asyncio.run(
            self._execute_adjust(
                panel,
                certification,
                username,
                password,
                base_url,
                command,
            )
        )

    async def _execute_adjust(
        self,
        panel,  # type: ignore[no-untyped-def]
        certification,  # type: ignore[no-untyped-def]
        username: str,
        password: str,
        base_url: str,
        command: ProviderMutationCommand,
    ) -> AdjustmentResult:
        transport: SanaeiAuthenticatedTransport | None = None
        try:
            try:
                transport = await SanaeiAuthenticatedTransport.authenticate(
                    base_url,
                    username,
                    password,
                    verify_tls=panel.tls_policy.verify_tls,
                )
            except PermissionError:
                return AdjustmentResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED")
            except ConnectionError:
                return AdjustmentResult("TRANSIENT_FAILURE", "PROVIDER_AUTH_UNAVAILABLE")
            result = await execute_certified_sanaei_adjust(
                SanaeiAdjustExecutor(transport, panel),
                panel,
                command,
                writes_enabled=True,
                detected_version=certification.detected_version,
                detected_digest=certification.contract_digest,
                certification_status=ProviderCertificationStatus(certification.status),
            )
            if result.outcome is MutationOutcome.SUCCESS:
                return AdjustmentResult("SUCCESS", result.safe_code)
            return AdjustmentResult(result.outcome.value, result.safe_code)
        finally:
            if transport is not None:
                await transport.aclose()
