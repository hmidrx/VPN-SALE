"""Database-selected, vault-backed production Sanaei provisioning composition."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from panel_adapters.contracts import CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.vault import EncryptedProviderCredential, ProviderCredentialVault
from panel_adapters.write_execution import (
    MutationOutcome,
    SanaeiAuthenticatedTransport,
    SanaeiCreateExecutor,
    execute_certified_sanaei_create,
)
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.providers import (
    DesiredRemoteIdentity,
    PanelCredentialReference,
    PanelEndpointPolicy,
    PanelInstance,
    PanelReference,
    PanelTlsPolicy,
    ProviderCertificationStatus,
    ProviderError,
    ProviderKind,
    ProviderMutationCommand,
    ProviderMutationOperation,
    RemoteExpiryPolicy,
    RemoteIdentifier,
    RemoteTrafficLimit,
)

from platform_api.order_models import OrderItemModel, OrderModel
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
)
from platform_api.service_models import (
    AllocationTargetModel,
    FulfillmentAllocationBindingModel,
    ServiceFulfillmentRequestModel,
)
from platform_worker.order_fulfillment import ProvisioningResult


class DatabaseSanaeiProvisioner:
    def __init__(self, factory: sessionmaker[Session], writes_enabled: bool) -> None:
        self.factory = factory
        self.writes_enabled = writes_enabled

    def provision(
        self, attempt: ServiceFulfillmentRequestModel, order: OrderModel, item: OrderItemModel
    ) -> ProvisioningResult:
        if not self.writes_enabled:
            return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")
        try:
            selected = self._select(attempt, item)
        except (ValueError, KeyError, ProviderError):
            return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_BLOCKED")
        panel, target, certification, login_name, login_credential = selected
        try:
            return asyncio.run(
                self._execute(
                    attempt,
                    order,
                    item,
                    panel,
                    target,
                    certification,
                    login_name,
                    login_credential,
                )
            )
        except ConnectionError:
            return ProvisioningResult("TRANSIENT_FAILURE", "PROVIDER_EXECUTION_UNAVAILABLE")

    def _select(self, attempt: ServiceFulfillmentRequestModel, item: OrderItemModel):
        selected_value = item.snapshot.get("selected_options")
        if not isinstance(selected_value, dict):
            raise ValueError("immutable selection missing")
        selected = cast(dict[str, object], selected_value)
        product_version_id = item.snapshot.get("product_version_id")
        location_code = selected.get("location_code")
        quality_code = selected.get("quality_code")
        if not all(
            isinstance(value, str) for value in (product_version_id, location_code, quality_code)
        ):
            raise ValueError("immutable allocation selection missing")
        with self.factory() as db:
            binding = db.scalar(
                select(FulfillmentAllocationBindingModel).where(
                    FulfillmentAllocationBindingModel.product_version_id == product_version_id,
                    FulfillmentAllocationBindingModel.location_code == location_code,
                    FulfillmentAllocationBindingModel.quality_code == quality_code,
                    FulfillmentAllocationBindingModel.status == "ACTIVE",
                )
            )
            if binding is None:
                raise ValueError("authoritative allocation binding unavailable")
            target = db.scalar(
                select(AllocationTargetModel)
                .where(
                    AllocationTargetModel.id == binding.allocation_target_id,
                    AllocationTargetModel.status.in_(("ACTIVE", "ENABLED")),
                    AllocationTargetModel.provider_kind == ProviderKind.SANAEI_3X_UI.value,
                )
                .with_for_update()
            )
            if target is None or target.required_protocol not in {"vless", "vmess"}:
                raise ValueError("bound allocation target unavailable")
            panel_row = db.get(PanelInstanceModel, target.panel_id)
            if panel_row is None or panel_row.status != "enabled":
                raise ValueError("panel unavailable")
            credential_row = db.scalar(
                select(PanelCredentialModel)
                .where(PanelCredentialModel.panel_instance_id == panel_row.id)
                .order_by(PanelCredentialModel.created_at.desc())
                .limit(1)
            )
            certification = db.scalar(
                select(ProviderConnectionTestModel)
                .where(ProviderConnectionTestModel.panel_instance_id == panel_row.id)
                .order_by(ProviderConnectionTestModel.tested_at.desc())
                .limit(1)
            )
            if credential_row is None or certification is None:
                raise ValueError("credential or certification unavailable")
            vault = ProviderCredentialVault.from_environment()
            plaintext = vault.decrypt_for_adapter(
                EncryptedProviderCredential(
                    credential_row.key_version,
                    credential_row.nonce_b64,
                    credential_row.ciphertext_b64,
                    credential_row.credential_kind,
                ),
                panel_row.id.encode(),
            )
            login_value: object = json.loads(plaintext)
            if not isinstance(login_value, dict):
                raise ValueError("credential invalid")
            login_fields = cast(dict[str, object], login_value)
            login_name = login_fields.get("username")
            login_credential = login_fields.get("password")
            if not isinstance(login_name, str) or not isinstance(login_credential, str):
                raise ValueError("credential invalid")
            panel = self._panel(panel_row, credential_row)
            return panel, target, certification, login_name, login_credential

    @staticmethod
    def _panel(row: PanelInstanceModel, credential: PanelCredentialModel) -> PanelInstance:
        tls = row.tls_policy
        endpoint = row.endpoint_policy
        return PanelInstance(
            UUID(row.id),
            PanelReference(row.public_reference),
            ProviderKind(row.provider_kind),
            row.display_name,
            row.endpoint_origin,
            row.base_path,
            row.status,
            PanelCredentialReference(
                UUID(credential.id), True, credential.credential_kind, credential.key_version
            ),
            PanelTlsPolicy(verify_tls=tls.get("verify_tls") is not False),
            PanelEndpointPolicy(
                allow_private_network=endpoint.get("allow_private_network") is True,
                allowed_ports=frozenset(
                    cast(list[int], endpoint.get("allowed_ports", [443, 8443]))
                ),
                require_https=endpoint.get("require_https") is not False,
            ),
            row.optimistic_version,
        )

    async def _execute(
        self,
        attempt: ServiceFulfillmentRequestModel,
        order: OrderModel,
        item: OrderItemModel,
        panel: PanelInstance,
        target: AllocationTargetModel,
        certification: ProviderConnectionTestModel,
        username: str,
        password: str,
    ) -> ProvisioningResult:
        selected = cast(dict[str, object], item.snapshot["selected_options"])
        contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
        if certification.detected_version not in {
            contract.release_tag,
            contract.release_tag.lstrip("v"),
        }:
            return ProvisioningResult(
                "REQUIRES_RECERTIFICATION", "PROVIDER_RECERTIFICATION_REQUIRED"
            )
        if certification.contract_digest != contract.contract_digest:
            return ProvisioningResult("CONTRACT_MISMATCH", "CONTRACT_MISMATCH")
        if certification.status != ProviderCertificationStatus.CONTRACT_VERIFIED.value:
            return ProvisioningResult(
                "REQUIRES_RECERTIFICATION", "PROVIDER_RECERTIFICATION_REQUIRED"
            )
        identity = RemoteIdentifier(attempt.remote_identity_uuid)
        inbound = RemoteIdentifier(target.inbound_id)
        command = ProviderMutationCommand(
            UUID(attempt.id),
            ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
            f"svc_{attempt.id[:24]}",
            f"customer_{order.customer_id[:12]}",
            panel.public_reference,
            "0.6a1",
            certification.detected_version or "",
            identity,
            (inbound,),
            DesiredRemoteIdentity(
                attempt.deduplication_key,
                target.required_protocol,
                True,
                RemoteTrafficLimit(int(cast(int, selected["traffic_bytes"]))),
                RemoteExpiryPolicy(None, no_expiry=True),
                int(cast(int, selected["device_count"])),
                "customer service",
                f"svc-{attempt.remote_identity_uuid.replace('-', '')[:20]}",
                (inbound,),
            ),
            None,
            attempt.deduplication_key,
            "fulfillment-worker",
            "paid order fulfillment",
            datetime.now(UTC),
            attempt.correlation_id,
            attempt.causation_id,
        )
        base_url = EndpointValidator().validate(
            panel.endpoint_origin + panel.base_path, panel.endpoint_policy, panel.tls_policy
        )
        transport: SanaeiAuthenticatedTransport | None = None
        try:
            transport = await SanaeiAuthenticatedTransport.authenticate(
                base_url, username, password, verify_tls=panel.tls_policy.verify_tls
            )
            result = await execute_certified_sanaei_create(
                SanaeiCreateExecutor(transport, panel),
                panel,
                command,
                writes_enabled=True,
                detected_version=certification.detected_version,
                detected_digest=certification.contract_digest,
                certification_status=ProviderCertificationStatus(certification.status),
            )
        except PermissionError:
            return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED")
        finally:
            if transport is not None:
                await transport.aclose()
        return ProvisioningResult(
            result.outcome.value,
            result.safe_code,
            None,
            {
                "allocation_target_id": target.id,
                "panel_reference": panel.public_reference,
                "provider_kind": ProviderKind.SANAEI_3X_UI.value,
                "contract_digest": contract.contract_digest,
            },
            False,
            str(result.remote_identity) if result.outcome is MutationOutcome.SUCCESS else None,
        )
