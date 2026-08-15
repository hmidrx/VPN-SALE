"""Database-selected, AEAD-vault-backed production Sanaei provisioning composition."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
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

from platform_api.fulfillment_runtime_models import (
    FulfillmentEntitlementClockModel,
    FulfillmentTargetBindingModel,
)
from platform_api.order_models import OrderItemModel, OrderModel
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
)
from platform_api.service_models import AllocationTargetModel, ServiceFulfillmentRequestModel
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
            panel, target, certification, login_name, login_passphrase = self._select(item)
            base_url = EndpointValidator().validate(
                panel.endpoint_origin + panel.base_path,
                panel.endpoint_policy,
                panel.tls_policy,
            )
        except (ProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_BLOCKED")
        return asyncio.run(
            self._execute(
                attempt,
                order,
                item,
                panel,
                target,
                certification,
                login_name,
                login_passphrase,
                base_url,
            )
        )

    def _select(
        self, item: OrderItemModel
    ) -> tuple[
        PanelInstance,
        AllocationTargetModel,
        ProviderConnectionTestModel,
        str,
        str,
    ]:
        selected_value = item.snapshot.get("selected_options")
        if not isinstance(selected_value, dict):
            raise ValueError("immutable selection missing")
        selected = cast(dict[str, object], selected_value)
        location_code = selected.get("location_code")
        quality_code = selected.get("quality_code")
        product_version_id = item.snapshot.get("product_version_id")
        if not all(isinstance(value, str) and value for value in (location_code, quality_code)):
            raise ValueError("immutable location/quality missing")
        if not isinstance(product_version_id, str) or not product_version_id:
            raise ValueError("immutable product version missing")

        requirements_value = item.snapshot.get("fulfillment_requirement_snapshot", [])
        if not isinstance(requirements_value, list):
            raise ValueError("immutable fulfillment requirements missing")
        requirements = cast(list[object], requirements_value)
        required_codes = {
            value["capability_code"]
            for raw in requirements
            if isinstance(raw, dict)
            for value in [cast(dict[str, object], raw)]
            if isinstance(value.get("capability_code"), str)
        }

        contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
        with self.factory() as db:
            bindings = list(
                db.scalars(
                    select(FulfillmentTargetBindingModel).where(
                        FulfillmentTargetBindingModel.product_version_id == product_version_id,
                        FulfillmentTargetBindingModel.location_code == location_code,
                        FulfillmentTargetBindingModel.quality_code == quality_code,
                        FulfillmentTargetBindingModel.active.is_(True),
                    )
                )
            )
            eligible: list[tuple[AllocationTargetModel, FulfillmentTargetBindingModel]] = []
            for binding in bindings:
                capability_codes = set(binding.capability_codes)
                if not required_codes.issubset(capability_codes):
                    continue
                target = db.get(AllocationTargetModel, binding.allocation_target_id)
                if target is None:
                    continue
                try:
                    inbound_number = int(target.inbound_id)
                except ValueError:
                    continue
                if (
                    target.status not in {"ACTIVE", "ENABLED"}
                    or target.provider_kind != ProviderKind.SANAEI_3X_UI.value
                    or target.required_protocol not in {"vless", "vmess"}
                    or inbound_number <= 0
                    or target.max_capacity <= target.safety_reserve
                ):
                    continue
                eligible.append((target, binding))
            if not eligible:
                raise ValueError("authoritative allocation binding unavailable")
            eligible.sort(key=lambda pair: (pair[0].priority, pair[0].id))
            target = eligible[0][0]

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
            if not credential_row.key_version.startswith("aead-"):
                raise ValueError("provider credential requires AEAD migration")
            if (
                certification.status != ProviderCertificationStatus.CONTRACT_VERIFIED.value
                or certification.detected_version
                not in {contract.release_tag, contract.release_tag.lstrip("v")}
                or certification.contract_digest != contract.contract_digest
            ):
                raise ValueError("provider certification unavailable or stale")

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
            secret_value: object = json.loads(plaintext)
            if not isinstance(secret_value, dict):
                raise ValueError("credential invalid")
            credential_fields = cast(dict[str, object], secret_value)
            login_name = credential_fields.get("username")
            login_passphrase = credential_fields.get("password")
            if not isinstance(login_name, str) or not isinstance(login_passphrase, str):
                raise ValueError("credential invalid")
            return (
                self._panel(panel_row, credential_row),
                target,
                certification,
                login_name,
                login_passphrase,
            )

    @staticmethod
    def _panel(row: PanelInstanceModel, credential: PanelCredentialModel) -> PanelInstance:
        tls = cast(dict[str, object], row.tls_policy)
        endpoint = cast(dict[str, object], row.endpoint_policy)
        allowed_ports_value = endpoint.get("allowed_ports", [443, 8443])
        if not isinstance(allowed_ports_value, list):
            raise ValueError("invalid endpoint port policy")
        allowed_ports_objects = cast(list[object], allowed_ports_value)
        if not all(type(value) is int for value in allowed_ports_objects):
            raise ValueError("invalid endpoint port policy")
        allowed_ports = frozenset(cast(list[int], allowed_ports_objects))
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
                allowed_ports=allowed_ports,
                require_https=endpoint.get("require_https") is not False,
            ),
            row.optimistic_version,
        )

    def _entitlement_clock(self, attempt_id: str, duration_days: int) -> tuple[datetime, datetime]:
        if duration_days <= 0:
            raise ValueError("duration must be positive")
        with self.factory.begin() as db:
            existing = db.get(FulfillmentEntitlementClockModel, attempt_id)
            if existing is not None:
                return existing.starts_at, existing.expires_at
            starts_at = datetime.now(UTC)
            expires_at = starts_at + timedelta(days=duration_days)
            db.add(
                FulfillmentEntitlementClockModel(
                    fulfillment_request_id=attempt_id,
                    starts_at=starts_at,
                    expires_at=expires_at,
                    created_at=starts_at,
                )
            )
            return starts_at, expires_at

    async def _execute(
        self,
        attempt: ServiceFulfillmentRequestModel,
        order: OrderModel,
        item: OrderItemModel,
        panel: PanelInstance,
        target: AllocationTargetModel,
        certification: ProviderConnectionTestModel,
        login_name: str,
        login_passphrase: str,
        base_url: str,
    ) -> ProvisioningResult:
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
                return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED")
            except ConnectionError:
                return ProvisioningResult("TRANSIENT_FAILURE", "PROVIDER_AUTH_UNAVAILABLE")

            selected = cast(dict[str, object], item.snapshot["selected_options"])
            duration_days = selected.get("duration_days")
            traffic_bytes = selected.get("traffic_bytes")
            device_count = selected.get("device_count")
            if (
                type(duration_days) is not int
                or type(traffic_bytes) is not int
                or type(device_count) is not int
                or duration_days <= 0
                or traffic_bytes < 0
                or device_count <= 0
            ):
                return ProvisioningResult(
                    "BLOCKED_BY_CONFIGURATION", "IMMUTABLE_ENTITLEMENT_INVALID"
                )
            starts_at, expires_at = self._entitlement_clock(attempt.id, duration_days)
            contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
            identity = RemoteIdentifier(attempt.remote_identity_uuid)
            inbound = RemoteIdentifier(target.inbound_id)
            command = ProviderMutationCommand(
                UUID(attempt.id),
                ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
                f"svc_{attempt.id[:24]}",
                f"customer_{order.customer_id[:12]}",
                panel.public_reference,
                contract.contract_digest,
                certification.detected_version or "",
                identity,
                (inbound,),
                DesiredRemoteIdentity(
                    attempt.deduplication_key,
                    target.required_protocol,
                    True,
                    RemoteTrafficLimit(traffic_bytes),
                    RemoteExpiryPolicy(expires_at),
                    device_count,
                    "customer service",
                    f"svc-{attempt.remote_identity_uuid.replace('-', '')[:20]}",
                    (inbound,),
                ),
                None,
                attempt.deduplication_key,
                "fulfillment-worker",
                "paid order fulfillment",
                starts_at,
                attempt.correlation_id,
                attempt.causation_id,
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
            return ProvisioningResult(
                result.outcome.value,
                result.safe_code,
                expires_at,
                {
                    "allocation_target_id": target.id,
                    "panel_reference": panel.public_reference,
                    "provider_kind": ProviderKind.SANAEI_3X_UI.value,
                    "contract_digest": contract.contract_digest,
                },
                False,
                str(result.remote_identity) if result.outcome is MutationOutcome.SUCCESS else None,
                starts_at,
            )
        finally:
            if transport is not None:
                await transport.aclose()
