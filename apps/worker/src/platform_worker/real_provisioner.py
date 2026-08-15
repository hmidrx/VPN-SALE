"""Database-selected, vault-backed production Sanaei provisioning composition."""

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
            selected = self._select(attempt, item)
        except (ValueError, KeyError):
            return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_SELECTION_BLOCKED")
        panel, target, certification, username, password = selected
        try:
            return asyncio.run(
                self._execute(
                    attempt,
                    order,
                    item,
                    panel,
                    target,
                    certification,
                    username,
                    password,
                )
            )
        except Exception:
            return ProvisioningResult("TRANSIENT_FAILURE", "PROVIDER_EXECUTION_UNAVAILABLE")

    def _select(self, attempt: ServiceFulfillmentRequestModel, item: OrderItemModel):
        selected_value = item.snapshot.get("selected_options")
        if not isinstance(selected_value, dict):
            raise ValueError("immutable selection missing")
        selected = cast(dict[str, object], selected_value)
        requirements_value = item.snapshot.get("fulfillment_requirement_snapshot", [])
        if not isinstance(requirements_value, list):
            raise ValueError("immutable fulfillment requirements missing")
        requirements = cast(list[object], requirements_value)
        with self.factory() as db:
            targets = db.scalars(
                select(AllocationTargetModel)
                .where(
                    AllocationTargetModel.status.in_(("ACTIVE", "ENABLED")),
                    AllocationTargetModel.provider_kind == ProviderKind.SANAEI_3X_UI.value,
                )
                .order_by(AllocationTargetModel.priority, AllocationTargetModel.id)
            ).all()
            target = next(
                (row for row in targets if self._eligible(row, selected, requirements)), None
            )
            if target is None:
                raise ValueError("eligible allocation target unavailable")
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
            secret_value: object = json.loads(plaintext)
            if not isinstance(secret_value, dict):
                raise ValueError("credential invalid")
            secret = cast(dict[str, object], secret_value)
            username, password = secret.get("username"), secret.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                raise ValueError("credential invalid")
            panel = self._panel(panel_row, credential_row)
            return panel, target, certification, username, password

    @staticmethod
    def _eligible(
        target: AllocationTargetModel,
        selected: dict[str, object],
        requirements: list[object],
    ) -> bool:
        diagnostic = target.safe_diagnostics
        locations = diagnostic.get("location_codes")
        qualities = diagnostic.get("quality_codes")
        capabilities = diagnostic.get("capability_codes")
        capability_codes: set[str] = (
            {value for value in cast(list[object], capabilities) if isinstance(value, str)}
            if isinstance(capabilities, list)
            else set[str]()
        )
        required_codes = {
            value["capability_code"]
            for item in requirements
            if isinstance(item, dict)
            for value in [cast(dict[str, object], item)]
            if isinstance(value.get("capability_code"), str)
        }
        return (
            isinstance(locations, list)
            and selected.get("location_code") in locations
            and isinstance(qualities, list)
            and selected.get("quality_code") in qualities
            and required_codes.issubset(capability_codes)
            and target.required_protocol in {"vless", "vmess"}
        )

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
        starts = order.paid_at or order.created_at
        expires = starts + timedelta(days=int(cast(int, selected["duration_days"])))
        contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
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
                RemoteExpiryPolicy(expires),
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
        delivery_ready = target.safe_diagnostics.get("delivery_ready") is True
        return ProvisioningResult(
            result.outcome.value,
            result.safe_code,
            expires,
            {
                "allocation_target_id": target.id,
                "panel_reference": panel.public_reference,
                "provider_kind": ProviderKind.SANAEI_3X_UI.value,
                "contract_digest": contract.contract_digest,
            },
            delivery_ready,
            str(result.remote_identity) if result.outcome is MutationOutcome.SUCCESS else None,
        )
