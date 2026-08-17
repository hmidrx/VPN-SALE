# pyright: reportPrivateUsage=false
"""Database-bound certified Sanaei executor for paid additive service operations."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import httpx
from panel_adapters.contracts import CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.sanaei_adjust_execution import (
    SanaeiAdjustExecutor,
    execute_certified_sanaei_adjust,
)
from panel_adapters.write_execution import MutationOutcome, SanaeiAuthenticatedTransport
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelInstance,
    ProviderCertificationStatus,
    ProviderError,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

from platform_api.provider_runtime_models import ProviderConnectionTestModel
from platform_api.service_models import (
    AllocationTargetModel,
    ServiceAttachmentModel,
    ServiceModel,
    ServiceOperationAttachmentPlanModel,
    ServiceOperationModel,
)
from platform_worker.real_activator import DatabaseSanaeiActivator
from platform_worker.service_operation_execution import ServiceOperationExecutionResult


class DatabaseSanaeiServiceOperationExecutor:
    def __init__(self, factory: sessionmaker[Session], writes_enabled: bool) -> None:
        self.factory = factory
        self.writes_enabled = writes_enabled
        self.context_loader = DatabaseSanaeiActivator(factory, writes_enabled)

    @staticmethod
    def _desired(
        operation: ServiceOperationModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> tuple[int | None, datetime | None, int | None]:
        desired_raw = plan.result_snapshot.get("desired_state")
        if not isinstance(desired_raw, dict):
            raise ValueError("desired state unavailable")
        desired = cast(dict[str, object], desired_raw)
        traffic_raw = desired.get("traffic_limit_bytes")
        expires_raw = desired.get("expires_at")
        device_limit = desired.get("device_limit")
        if device_limit is not None and (type(device_limit) is not int or device_limit <= 0):
            raise ValueError("desired device limit invalid")

        traffic: int | None = None
        expires_at: datetime | None = None
        if operation.operation_type == "RENEW":
            if not isinstance(expires_raw, str):
                raise ValueError("renewal expiry target unavailable")
            expires_at = datetime.fromisoformat(expires_raw)
            if expires_at.tzinfo is None:
                raise ValueError("desired expiry must be timezone aware")
        elif operation.operation_type == "ADD_TRAFFIC":
            if type(traffic_raw) is not int or traffic_raw <= 0:
                raise ValueError("traffic target unavailable")
            traffic = traffic_raw
        else:
            raise ValueError("service operation unsupported")
        return traffic, expires_at, cast(int | None, device_limit)

    def execute(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> ServiceOperationExecutionResult:
        if not self.writes_enabled:
            return ServiceOperationExecutionResult(
                "BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED"
            )
        try:
            panel, target, certification, username, password = self.context_loader._select(
                attachment
            )
            traffic, expires_at, device_limit = self._desired(operation, plan)
            if not attachment.remote_identity_reference or not plan.provider_operation_id:
                raise ValueError("remote or provider operation identity unavailable")
            remote_identity = str(UUID(attachment.remote_identity_reference))
            operation_uuid = UUID(plan.provider_operation_id)
            base_url = EndpointValidator().validate(
                panel.endpoint_origin + panel.base_path,
                panel.endpoint_policy,
                panel.tls_policy,
            )
        except (ProviderError, ValueError, KeyError, TypeError):
            return ServiceOperationExecutionResult(
                "BLOCKED_BY_CONFIGURATION", "SERVICE_OPERATION_SELECTION_BLOCKED"
            )
        return asyncio.run(
            self._execute(
                operation,
                service,
                panel,
                target,
                certification,
                username,
                password,
                base_url,
                remote_identity,
                operation_uuid,
                traffic,
                expires_at,
                device_limit,
                plan,
            )
        )

    async def _execute(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        panel: PanelInstance,
        target: AllocationTargetModel,
        certification: ProviderConnectionTestModel,
        username: str,
        password: str,
        base_url: str,
        remote_identity: str,
        operation_uuid: UUID,
        traffic: int | None,
        expires_at: datetime | None,
        device_limit: int | None,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> ServiceOperationExecutionResult:
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
                return ServiceOperationExecutionResult(
                    "BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED"
                )
            except ConnectionError:
                return ServiceOperationExecutionResult(
                    "TRANSIENT_FAILURE", "PROVIDER_AUTH_UNAVAILABLE"
                )

            contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
            inbound = RemoteIdentifier(target.inbound_id)
            provider_label = f"svc-{remote_identity.replace('-', '')[:20]}"
            traffic_policy = (
                RemoteTrafficLimit(traffic)
                if traffic is not None
                else RemoteTrafficLimit(None, unlimited=True)
            )
            expiry_policy = (
                RemoteExpiryPolicy(expires_at)
                if expires_at is not None
                else RemoteExpiryPolicy(None, no_expiry=True)
            )
            command = ProviderMutationCommand(
                operation_id=operation_uuid,
                operation=ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
                service_reference=service.public_reference,
                customer_reference=f"customer_{service.beneficiary_customer_id[:12]}",
                panel_reference=panel.public_reference,
                adapter_contract_version=contract.contract_digest,
                expected_panel_version=certification.detected_version or "",
                target_remote_identity=RemoteIdentifier(remote_identity),
                target_inbound_relationships=(inbound,),
                desired_state=DesiredRemoteIdentity(
                    shop_identity_reference=service.public_reference,
                    protocol=target.required_protocol,
                    enabled=True,
                    traffic_limit=traffic_policy,
                    expiry=expiry_policy,
                    device_or_ip_limit=device_limit,
                    customer_safe_remark="customer service",
                    provider_safe_label=provider_label,
                    inbound_assignments=(inbound,),
                ),
                expected_remote_snapshot=None,
                idempotency_scope=f"service-operation:v1:{operation.id}:{plan.attachment_id}",
                actor_reference="service-operation-worker",
                reason=f"paid additive {operation.operation_type.lower()} operation",
                requested_at=datetime.now(UTC),
                correlation_reference=f"service-operation:{operation.id}",
                causation_reference=operation.id,
            )
            try:
                result = await execute_certified_sanaei_adjust(
                    SanaeiAdjustExecutor(transport, panel),
                    panel,
                    command,
                    writes_enabled=True,
                    detected_version=certification.detected_version,
                    detected_digest=certification.contract_digest,
                    certification_status=ProviderCertificationStatus(certification.status),
                )
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPError, ConnectionError):
                return ServiceOperationExecutionResult(
                    "TRANSIENT_FAILURE", "PROVIDER_EXECUTION_UNAVAILABLE"
                )
            except ProviderError:
                return ServiceOperationExecutionResult(
                    "BLOCKED_BY_CONFIGURATION", "PROVIDER_EXECUTION_BLOCKED"
                )
            if result.outcome is MutationOutcome.SUCCESS:
                return ServiceOperationExecutionResult("SUCCESS", result.safe_code)
            return ServiceOperationExecutionResult(result.outcome.value, result.safe_code)
        finally:
            if transport is not None:
                await transport.aclose()
