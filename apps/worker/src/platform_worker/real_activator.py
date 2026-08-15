# pyright: reportPrivateUsage=false
"""Provider-backed service activation after durable provisioning succeeds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from panel_adapters.contracts import CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.write_execution import (
    MutationOutcome,
    SanaeiAuthenticatedTransport,
    SanaeiUpdateExecutor,
    execute_certified_sanaei_update,
)
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    ProviderCertificationStatus,
    ProviderError,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

from platform_api.activation_models import ServiceActivationRequestModel
from platform_api.delivery_secrets import DeliveryPayloadCipher, DeliveryPayloadError
from platform_api.order_models import OrderItemModel, OrderModel
from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceFulfillmentRequestModel,
    ServiceModel,
)
from platform_worker.real_provisioner import DatabaseSanaeiProvisioner


@dataclass(frozen=True)
class ActivationProviderResult:
    outcome: str
    safe_code: str
    links: tuple[str, ...] = ()


class DatabaseSanaeiActivator:
    """Reuse the immutable BOT-2A.1 allocation selection and activate that exact identity."""

    def __init__(self, factory: sessionmaker[Session], writes_enabled: bool) -> None:
        self.factory = factory
        self.writes_enabled = writes_enabled
        self._selector = DatabaseSanaeiProvisioner(factory, writes_enabled)

    def activate(
        self,
        activation: ServiceActivationRequestModel,
        service: ServiceModel,
        fulfillment: ServiceFulfillmentRequestModel,
        attachment: ServiceAttachmentModel,
        order: OrderModel,
        item: OrderItemModel,
    ) -> ActivationProviderResult:
        if not self.writes_enabled:
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")
        if activation.activation_instant is None or activation.expires_at is None:
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "ACTIVATION_CLOCK_MISSING")
        if not attachment.remote_identity_reference:
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "REMOTE_IDENTITY_MISSING")
        if attachment.remote_identity_reference != fulfillment.remote_identity_uuid:
            return ActivationProviderResult("PERMANENT_FAILURE", "REMOTE_IDENTITY_MISMATCH")
        try:
            panel, target, certification, login_name, login_passphrase = self._selector._select(item)
            if target.id != attachment.allocation_target_id:
                return ActivationProviderResult(
                    "BLOCKED_BY_CONFIGURATION", "ALLOCATION_TARGET_CHANGED"
                )
            base_url = EndpointValidator().validate(
                panel.endpoint_origin + panel.base_path,
                panel.endpoint_policy,
                panel.tls_policy,
            )
        except (ProviderError, ValueError, KeyError, TypeError):
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_BLOCKED")
        return asyncio.run(
            self._execute(
                activation,
                service,
                fulfillment,
                attachment,
                order,
                item,
                panel,
                target.inbound_id,
                target.required_protocol,
                certification,
                login_name,
                login_passphrase,
                base_url,
            )
        )

    async def _execute(
        self,
        activation: ServiceActivationRequestModel,
        service: ServiceModel,
        fulfillment: ServiceFulfillmentRequestModel,
        attachment: ServiceAttachmentModel,
        order: OrderModel,
        item: OrderItemModel,
        panel: object,
        inbound_id: str,
        protocol: str,
        certification: object,
        login_name: str,
        login_passphrase: str,
        base_url: str,
    ) -> ActivationProviderResult:
        from vpnsale_domain.providers import PanelInstance
        from platform_api.provider_runtime_models import ProviderConnectionTestModel

        if not isinstance(panel, PanelInstance) or not isinstance(
            certification, ProviderConnectionTestModel
        ):
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_INVALID")
        transport: SanaeiAuthenticatedTransport | None = None
        try:
            try:
                transport = await SanaeiAuthenticatedTransport.authenticate(
                    base_url,
                    login_name,
                    login_passphrase,
                    verify_tls=panel.tls_policy.verify_tls,
                )
            except PermissionError:
                return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED")
            except ConnectionError:
                return ActivationProviderResult("TRANSIENT_FAILURE", "PROVIDER_AUTH_UNAVAILABLE")

            provider_label = f"svc-{fulfillment.remote_identity_uuid.replace('-', '')[:20]}"
            executor = SanaeiUpdateExecutor(transport, panel)
            raw_links = await executor.fetch_links(provider_label)
            if raw_links is None:
                return ActivationProviderResult("TRANSIENT_FAILURE", "DELIVERY_LINKS_UNAVAILABLE")
            try:
                links = DeliveryPayloadCipher.validate_links(list(raw_links))
            except DeliveryPayloadError:
                return ActivationProviderResult("CONTRACT_MISMATCH", "DELIVERY_LINKS_INVALID")

            snapshot = service.entitlement_snapshot
            traffic_bytes = snapshot.get("traffic_quota_bytes")
            device_limit = snapshot.get("device_limit")
            if (
                type(traffic_bytes) is not int
                or traffic_bytes <= 0
                or type(device_limit) is not int
                or device_limit <= 0
            ):
                return ActivationProviderResult(
                    "BLOCKED_BY_CONFIGURATION", "IMMUTABLE_ENTITLEMENT_INVALID"
                )
            contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
            command = ProviderMutationCommand(
                UUID(activation.id),
                ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
                service.public_reference,
                f"customer_{order.customer_id[:12]}",
                panel.public_reference,
                contract.contract_digest,
                certification.detected_version or "",
                RemoteIdentifier(fulfillment.remote_identity_uuid),
                (RemoteIdentifier(inbound_id),),
                DesiredRemoteIdentity(
                    fulfillment.deduplication_key,
                    protocol,
                    True,
                    RemoteTrafficLimit(traffic_bytes),
                    RemoteExpiryPolicy(activation.expires_at),
                    device_limit,
                    "customer service",
                    provider_label,
                    (RemoteIdentifier(inbound_id),),
                ),
                f"provider-created-disabled:{fulfillment.remote_identity_uuid}",
                f"activation:{activation.id}",
                "activation-worker",
                "activate paid service for customer delivery",
                datetime.now(UTC),
                fulfillment.correlation_id,
                fulfillment.id,
            )
            result = await execute_certified_sanaei_update(
                executor,
                panel,
                command,
                writes_enabled=True,
                detected_version=certification.detected_version,
                detected_digest=certification.contract_digest,
                certification_status=ProviderCertificationStatus(certification.status),
            )
            return ActivationProviderResult(result.outcome.value, result.safe_code, links)
        finally:
            if transport is not None:
                await transport.aclose()
