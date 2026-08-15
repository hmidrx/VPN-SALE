# pyright: reportPrivateUsage=false
"""Provider-backed service activation after durable provisioning succeeds."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from panel_adapters.contracts import CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.write_execution import (
    SanaeiAuthenticatedTransport,
    SanaeiUpdateExecutor,
    execute_certified_sanaei_update,
)
from sqlalchemy import select
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
from platform_api.delivery_models import DeliveryRevisionModel
from platform_api.delivery_secrets import DeliveryPayloadCipher, DeliveryPayloadError
from platform_api.fulfillment_runtime_models import FulfillmentEntitlementClockModel
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


class DatabaseSanaeiActivator:
    """Activate the exact identity/target selected by BOT-2A.1, never a new target."""

    def __init__(self, factory: sessionmaker[Session], writes_enabled: bool) -> None:
        self.factory = factory
        self.writes_enabled = writes_enabled
        self._selector = DatabaseSanaeiProvisioner(factory, writes_enabled)

    def activate(self, activation_id: str) -> ActivationProviderResult:
        if not self.writes_enabled:
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")
        try:
            with self.factory() as db:
                activation = db.get(ServiceActivationRequestModel, activation_id)
                if activation is None:
                    return ActivationProviderResult("PERMANENT_FAILURE", "ACTIVATION_REQUEST_MISSING")
                service = db.get(ServiceModel, activation.service_id)
                fulfillment = db.get(
                    ServiceFulfillmentRequestModel, activation.fulfillment_request_id
                )
                if service is None or fulfillment is None:
                    return ActivationProviderResult("PERMANENT_FAILURE", "ACTIVATION_STATE_MISSING")
                attachment = db.scalar(
                    select(ServiceAttachmentModel).where(
                        ServiceAttachmentModel.service_id == service.id,
                        ServiceAttachmentModel.required.is_(True),
                    )
                )
                item = db.get(OrderItemModel, fulfillment.order_item_id)
                order = db.get(OrderModel, fulfillment.order_id)
                if attachment is None or item is None or order is None:
                    return ActivationProviderResult("PERMANENT_FAILURE", "ACTIVATION_INPUT_MISSING")
                if not attachment.remote_identity_reference:
                    return ActivationProviderResult(
                        "BLOCKED_BY_CONFIGURATION", "REMOTE_IDENTITY_MISSING"
                    )
                if attachment.remote_identity_reference != fulfillment.remote_identity_uuid:
                    return ActivationProviderResult("PERMANENT_FAILURE", "REMOTE_IDENTITY_MISMATCH")
                panel, target, certification, login_name, login_passphrase = self._selector._select(
                    item
                )
                if target.id != attachment.allocation_target_id:
                    return ActivationProviderResult(
                        "BLOCKED_BY_CONFIGURATION", "ALLOCATION_TARGET_CHANGED"
                    )
                base_url = EndpointValidator().validate(
                    panel.endpoint_origin + panel.base_path,
                    panel.endpoint_policy,
                    panel.tls_policy,
                )
                state = (
                    service.id,
                    fulfillment.id,
                    fulfillment.remote_identity_uuid,
                    fulfillment.deduplication_key,
                    fulfillment.correlation_id,
                    order.customer_id,
                    target.id,
                    target.inbound_id,
                    target.required_protocol,
                    dict(service.entitlement_snapshot),
                    attachment.id,
                )
        except (ProviderError, ValueError, KeyError, TypeError):
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_BLOCKED")

        return asyncio.run(
            self._execute(
                activation_id,
                state,
                panel,
                certification,
                login_name,
                login_passphrase,
                base_url,
            )
        )

    def _stage_delivery_and_clock(
        self,
        activation_id: str,
        service_id: str,
        fulfillment_id: str,
        attachment_id: str,
        allocation_target_id: str,
        remote_identity: str,
        entitlement: dict[str, object],
        links: tuple[str, ...],
    ) -> tuple[datetime, datetime]:
        duration_days = entitlement.get("duration_days")
        if type(duration_days) is not int or duration_days <= 0:
            raise ValueError("immutable duration invalid")
        cipher = DeliveryPayloadCipher.from_environment()
        validated = cipher.validate_links(list(links))
        encrypted = cipher.encrypt(service_id, validated)
        now = datetime.now(UTC)
        with self.factory.begin() as db:
            activation = db.scalar(
                select(ServiceActivationRequestModel)
                .where(ServiceActivationRequestModel.id == activation_id)
                .with_for_update()
            )
            if activation is None:
                raise ValueError("activation request disappeared")
            if activation.activation_instant is None:
                activation.activation_instant = now
                activation.expires_at = now + timedelta(days=duration_days)
            if activation.expires_at is None:
                raise ValueError("activation expiry missing")
            clock = db.get(FulfillmentEntitlementClockModel, fulfillment_id)
            if clock is None:
                db.add(
                    FulfillmentEntitlementClockModel(
                        fulfillment_request_id=fulfillment_id,
                        starts_at=activation.activation_instant,
                        expires_at=activation.expires_at,
                        created_at=now,
                    )
                )
            elif (
                clock.starts_at != activation.activation_instant
                or clock.expires_at != activation.expires_at
            ):
                raise ValueError("entitlement clock conflict")

            staged = db.scalar(
                select(DeliveryRevisionModel)
                .where(
                    DeliveryRevisionModel.service_id == service_id,
                    DeliveryRevisionModel.status == "STAGED",
                )
                .order_by(DeliveryRevisionModel.revision_number.desc())
                .limit(1)
                .with_for_update()
            )
            if staged is None:
                latest = db.scalar(
                    select(DeliveryRevisionModel)
                    .where(DeliveryRevisionModel.service_id == service_id)
                    .order_by(DeliveryRevisionModel.revision_number.desc())
                    .limit(1)
                )
                staged = DeliveryRevisionModel(
                    service_id=service_id,
                    revision_number=(latest.revision_number + 1) if latest else 1,
                    status="STAGED",
                    attachment_snapshot={
                        "attachment_id": attachment_id,
                        "allocation_target_id": allocation_target_id,
                        "link_count": len(validated),
                        "provider_verified": True,
                    },
                    renderer_versions={"provider_links": "sanaei-3x-ui-v3.5.0"},
                    credential_fingerprints={
                        "remote_identity": "sha256:"
                        + hashlib.sha256(remote_identity.encode()).hexdigest()
                    },
                    compatibility_state={"plain_links": True, "base64_links": True},
                    reason="INITIAL_ACTIVATION",
                    correlation_reference=f"activation:{activation_id}",
                    encrypted_payload=encrypted.ciphertext,
                    encryption_key_version=encrypted.key_version,
                    payload_sha256=encrypted.sha256,
                    created_at=now,
                )
                db.add(staged)
            else:
                staged.attachment_snapshot = {
                    "attachment_id": attachment_id,
                    "allocation_target_id": allocation_target_id,
                    "link_count": len(validated),
                    "provider_verified": True,
                }
                staged.encrypted_payload = encrypted.ciphertext
                staged.encryption_key_version = encrypted.key_version
                staged.payload_sha256 = encrypted.sha256
            activation.updated_at = now
            return activation.activation_instant, activation.expires_at

    async def _execute(
        self,
        activation_id: str,
        state: tuple[
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            str,
            dict[str, object],
            str,
        ],
        panel: object,
        certification: object,
        login_name: str,
        login_passphrase: str,
        base_url: str,
    ) -> ActivationProviderResult:
        from platform_api.provider_runtime_models import ProviderConnectionTestModel
        from vpnsale_domain.providers import PanelInstance

        if not isinstance(panel, PanelInstance) or not isinstance(
            certification, ProviderConnectionTestModel
        ):
            return ActivationProviderResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_INVALID")
        (
            service_id,
            fulfillment_id,
            remote_identity,
            deduplication_key,
            correlation_id,
            customer_id,
            allocation_target_id,
            inbound_id,
            protocol,
            entitlement,
            attachment_id,
        ) = state
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

            provider_label = f"svc-{remote_identity.replace('-', '')[:20]}"
            executor = SanaeiUpdateExecutor(transport, panel)
            raw_links = await executor.fetch_links(provider_label)
            if raw_links is None:
                return ActivationProviderResult("TRANSIENT_FAILURE", "DELIVERY_LINKS_UNAVAILABLE")
            try:
                activation_instant, expires_at = self._stage_delivery_and_clock(
                    activation_id,
                    service_id,
                    fulfillment_id,
                    attachment_id,
                    allocation_target_id,
                    remote_identity,
                    entitlement,
                    raw_links,
                )
            except DeliveryPayloadError:
                return ActivationProviderResult(
                    "BLOCKED_BY_CONFIGURATION", "DELIVERY_ENCRYPTION_UNAVAILABLE"
                )
            except ValueError:
                return ActivationProviderResult(
                    "BLOCKED_BY_CONFIGURATION", "ACTIVATION_STAGING_BLOCKED"
                )

            traffic_bytes = entitlement.get("traffic_quota_bytes")
            device_limit = entitlement.get("device_limit")
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
                UUID(activation_id),
                ProviderMutationOperation.UPDATE_REMOTE_IDENTITY,
                service_id,
                f"customer_{customer_id[:12]}",
                panel.public_reference,
                contract.contract_digest,
                certification.detected_version or "",
                RemoteIdentifier(remote_identity),
                (RemoteIdentifier(inbound_id),),
                DesiredRemoteIdentity(
                    deduplication_key,
                    protocol,
                    True,
                    RemoteTrafficLimit(cast(int, traffic_bytes)),
                    RemoteExpiryPolicy(expires_at),
                    cast(int, device_limit),
                    "customer service",
                    provider_label,
                    (RemoteIdentifier(inbound_id),),
                ),
                f"provider-created-disabled:{remote_identity}:{activation_instant.isoformat()}",
                f"activation:{activation_id}",
                "activation-worker",
                "activate paid service for customer delivery",
                datetime.now(UTC),
                correlation_id,
                fulfillment_id,
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
            return ActivationProviderResult(result.outcome.value, result.safe_code)
        finally:
            if transport is not None:
                await transport.aclose()
