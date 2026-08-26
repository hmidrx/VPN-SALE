"""Quote-pinned, AEAD-vault-backed Sanaei/3x-ui v3.7.0 provisioning."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from panel_adapters.contracts import EndpointValidator
from panel_adapters.sanaei_3x_ui_v370 import (
    SANAEI_3X_UI_V370_CONTRACT,
    HttpxSanaei3xUiV370Transport,
)
from panel_adapters.sanaei_3x_ui_v370_execution import (
    Sanaei3xUiV370Executor,
    execute_v370_mutation,
)
from panel_adapters.vault import EncryptedProviderCredential, ProviderCredentialVault
from panel_adapters.write_execution import MutationOutcome
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

from platform_api.fulfillment_runtime_models import FulfillmentTargetBindingModel
from platform_api.order_models import OrderItemModel, OrderModel
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
)
from platform_api.service_models import AllocationTargetModel, ServiceFulfillmentRequestModel
from platform_api.services import select_runtime_allocation_targets
from platform_worker.order_fulfillment import ProvisioningResult
from platform_worker.provider_v370_connection import connect_v370


@dataclass(frozen=True)
class _Selection:
    panel: PanelInstance
    targets: tuple[AllocationTargetModel, ...]
    certification: ProviderConnectionTestModel
    credential: dict[str, object]
    policy_version_id: str | None


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
            endpoint_origin = EndpointValidator().validate(
                selected.panel.endpoint_origin,
                selected.panel.endpoint_policy,
                selected.panel.tls_policy,
            )
        except (ProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_BLOCKED")
        return asyncio.run(self._execute(attempt, order, item, selected, endpoint_origin))

    def _select(self, attempt: ServiceFulfillmentRequestModel, item: OrderItemModel) -> _Selection:
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

        policy_snapshot = item.snapshot.get("allocation_policy_snapshot")
        policy_version_id: str | None = None
        with self.factory() as db:
            targets: tuple[AllocationTargetModel, ...]
            if isinstance(policy_snapshot, dict):
                policy_mapping = cast(dict[str, object], policy_snapshot)
            else:
                policy_mapping = {}
            if isinstance(policy_mapping.get("policy_version_id"), str):
                policy_version_id = cast(str, policy_mapping["policy_version_id"])
                _policy, targets = select_runtime_allocation_targets(
                    db,
                    policy_version_id=policy_version_id,
                    decision_key=attempt.deduplication_key,
                )
            else:
                # Migration-only compatibility for already-paid v1 orders. New checkout
                # always persists an allocation policy version.
                targets = self._legacy_targets(
                    db,
                    item,
                    product_version_id,
                    cast(str, location_code),
                    cast(str, quality_code),
                )
            if not targets or len({row.panel_id for row in targets}) != 1:
                raise ValueError("authoritative same-panel target selection unavailable")
            if len({row.required_protocol for row in targets}) != 1:
                raise ValueError("multi-inbound protocol mismatch")
            panel_row = db.get(PanelInstanceModel, targets[0].panel_id)
            if panel_row is None or panel_row.status.upper() not in {"ACTIVE", "ENABLED"}:
                raise ValueError("panel unavailable")
            try:
                target_invalid = any(
                    target.status.upper() not in {"ACTIVE", "ENABLED"}
                    or target.provider_kind != ProviderKind.SANAEI_3X_UI.value
                    or target.required_protocol not in {"vless", "vmess"}
                    or int(target.inbound_id) <= 0
                    for target in targets
                )
            except ValueError as exc:
                raise ValueError("allocation inbound invalid") from exc
            if target_invalid:
                raise ValueError("allocation target unavailable")
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
            contract = SANAEI_3X_UI_V370_CONTRACT
            if (
                certification.status != ProviderCertificationStatus.CONTRACT_VERIFIED.value
                or certification.detected_version
                not in {contract.release_tag, contract.release_tag.lstrip("v")}
                or certification.contract_digest != contract.contract_digest
            ):
                raise ValueError("v3.7.0 provider certification unavailable or stale")
            credential = self._decrypt_credential(panel_row.id, credential_row)
            return _Selection(
                self._panel(panel_row, credential_row),
                targets,
                certification,
                credential,
                policy_version_id,
            )

    @staticmethod
    def _legacy_targets(
        db: Session,
        item: OrderItemModel,
        product_version_id: str,
        location_code: str,
        quality_code: str,
    ) -> tuple[AllocationTargetModel, ...]:
        requirements_value = item.snapshot.get("fulfillment_requirement_snapshot", [])
        if not isinstance(requirements_value, list):
            raise ValueError("immutable fulfillment requirements missing")
        required_codes = {
            value["capability_code"]
            for raw in cast(list[object], requirements_value)
            if isinstance(raw, dict)
            for value in [cast(dict[str, object], raw)]
            if isinstance(value.get("capability_code"), str)
        }
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
        eligible: list[AllocationTargetModel] = []
        for binding in bindings:
            if not required_codes.issubset(set(binding.capability_codes)):
                continue
            target = db.get(AllocationTargetModel, binding.allocation_target_id)
            if target is not None:
                eligible.append(target)
        eligible.sort(key=lambda value: (value.priority, value.id))
        return tuple(eligible[:1])

    @staticmethod
    def _decrypt_credential(
        panel_id: str, credential_row: PanelCredentialModel
    ) -> dict[str, object]:
        plaintext = ProviderCredentialVault.from_environment().decrypt_for_adapter(
            EncryptedProviderCredential(
                credential_row.key_version,
                credential_row.nonce_b64,
                credential_row.ciphertext_b64,
                credential_row.credential_kind,
            ),
            f"panel:{panel_id}".encode(),
        )
        secret_value: object = json.loads(plaintext)
        if not isinstance(secret_value, dict):
            raise ValueError("credential invalid")
        credential = cast(dict[str, object], secret_value)
        if credential.get("auth_mode") != credential_row.credential_kind:
            raise ValueError("credential mode mismatch")
        return credential

    @staticmethod
    def _panel(row: PanelInstanceModel, credential: PanelCredentialModel) -> PanelInstance:
        tls = row.tls_policy
        endpoint = row.endpoint_policy
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

    async def _execute(
        self,
        attempt: ServiceFulfillmentRequestModel,
        order: OrderModel,
        item: OrderItemModel,
        selected_context: _Selection,
        endpoint_origin: str,
    ) -> ProvisioningResult:
        transport: HttpxSanaei3xUiV370Transport | None = None
        try:
            try:
                transport, client = await connect_v370(
                    selected_context.panel,
                    endpoint_origin,
                    selected_context.credential,
                )
            except PermissionError:
                return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED")
            except (ConnectionError, OSError):
                return ProvisioningResult("TRANSIENT_FAILURE", "PROVIDER_AUTH_UNAVAILABLE")
            except (ProviderError, ValueError):
                return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_BLOCKED")

            selected_options = cast(dict[str, object], item.snapshot["selected_options"])
            duration_days = selected_options.get("duration_days")
            traffic_bytes = selected_options.get("traffic_bytes")
            device_count = selected_options.get("device_count")
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

            requested_at = datetime.now(UTC)
            contract = SANAEI_3X_UI_V370_CONTRACT
            targets = selected_context.targets
            identity = RemoteIdentifier(attempt.remote_identity_uuid)
            inbounds = tuple(RemoteIdentifier(target.inbound_id) for target in targets)
            operation_id = uuid5(
                NAMESPACE_URL,
                f"vpnsale:v370:create:{attempt.id}:{selected_context.panel.public_reference}",
            )
            command = ProviderMutationCommand(
                operation_id,
                ProviderMutationOperation.CREATE_REMOTE_IDENTITY,
                f"svc_{attempt.id[:24]}",
                f"customer_{order.customer_id[:12]}",
                selected_context.panel.public_reference,
                contract.contract_digest,
                selected_context.certification.detected_version or "",
                identity,
                inbounds,
                DesiredRemoteIdentity(
                    attempt.deduplication_key,
                    targets[0].required_protocol,
                    False,
                    RemoteTrafficLimit(traffic_bytes),
                    RemoteExpiryPolicy(None, no_expiry=True),
                    device_count,
                    "customer service",
                    f"svc-{attempt.remote_identity_uuid.replace('-', '')[:20]}",
                    inbounds,
                ),
                None,
                attempt.deduplication_key,
                "fulfillment-worker",
                "paid order fulfillment pending delivery activation",
                requested_at,
                attempt.correlation_id,
                attempt.causation_id,
            )
            result = await execute_v370_mutation(
                Sanaei3xUiV370Executor(client),
                selected_context.panel,
                command,
                writes_enabled=True,
                detected_version=selected_context.certification.detected_version,
                detected_digest=selected_context.certification.contract_digest,
                certification_status=ProviderCertificationStatus(
                    selected_context.certification.status
                ),
            )
            return ProvisioningResult(
                result.outcome.value,
                result.safe_code,
                None,
                {
                    "allocation_target_id": targets[0].id,
                    "allocation_target_ids": [target.id for target in targets],
                    "inbound_ids": [target.inbound_id for target in targets],
                    "panel_reference": selected_context.panel.public_reference,
                    "provider_kind": ProviderKind.SANAEI_3X_UI.value,
                    "provider_version": contract.release_tag,
                    "contract_digest": contract.contract_digest,
                    "allocation_policy_version_id": selected_context.policy_version_id,
                    "entitlement_start_policy": "DELIVERY_ACTIVATION",
                },
                False,
                str(result.remote_identity) if result.outcome is MutationOutcome.SUCCESS else None,
                None,
            )
        finally:
            if transport is not None:
                await transport.aclose()
