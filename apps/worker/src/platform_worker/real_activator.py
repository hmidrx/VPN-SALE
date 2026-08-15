"""Database-bound, certified Sanaei activation composition for provisioned services."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from panel_adapters.activation_execution import (
    SanaeiActivationExecutor,
    execute_certified_sanaei_activation,
)
from panel_adapters.contracts import CERTIFIED_CONTRACTS, EndpointValidator
from panel_adapters.vault import EncryptedProviderCredential, ProviderCredentialVault
from panel_adapters.write_execution import MutationOutcome, SanaeiAuthenticatedTransport
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

from platform_api.activation_models import ServiceActivationRequestModel
from platform_api.provider_runtime_models import (
    PanelCredentialModel,
    PanelInstanceModel,
    ProviderConnectionTestModel,
)
from platform_api.service_models import AllocationTargetModel, ServiceAttachmentModel, ServiceModel
from platform_worker.service_activation import ActivationResult


class DatabaseSanaeiActivator:
    def __init__(self, factory: sessionmaker[Session], writes_enabled: bool) -> None:
        self.factory = factory
        self.writes_enabled = writes_enabled

    def activate(
        self,
        request: ServiceActivationRequestModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
    ) -> ActivationResult:
        if not self.writes_enabled:
            return ActivationResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")
        try:
            (
                panel,
                target,
                certification,
                login_name,
                login_passphrase,
            ) = self._select(attachment)
            base_url = EndpointValidator().validate(
                panel.endpoint_origin + panel.base_path,
                panel.endpoint_policy,
                panel.tls_policy,
            )
            duration_days, traffic_bytes, device_limit = self._entitlement(service)
            remote_identity = self._remote_identity(attachment)
        except (ProviderError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return ActivationResult("BLOCKED_BY_CONFIGURATION", "ACTIVATION_SELECTION_BLOCKED")

        activation_at = datetime.now(UTC)
        expires_at = activation_at + timedelta(days=duration_days)
        return asyncio.run(
            self._execute(
                request,
                service,
                panel,
                target,
                certification,
                login_name,
                login_passphrase,
                base_url,
                remote_identity,
                traffic_bytes,
                device_limit,
                activation_at,
                expires_at,
            )
        )

    @staticmethod
    def _entitlement(service: ServiceModel) -> tuple[int, int, int]:
        snapshot = service.entitlement_snapshot
        duration_days = snapshot.get("duration_days")
        traffic_bytes = snapshot.get("traffic_quota_bytes")
        device_limit = snapshot.get("device_limit")
        if (
            type(duration_days) is not int
            or type(traffic_bytes) is not int
            or type(device_limit) is not int
            or duration_days <= 0
            or traffic_bytes <= 0
            or device_limit <= 0
        ):
            raise ValueError("service entitlement invalid")
        return duration_days, traffic_bytes, device_limit

    @staticmethod
    def _remote_identity(attachment: ServiceAttachmentModel) -> str:
        value = attachment.remote_identity_reference
        if not value:
            raise ValueError("remote identity unavailable")
        # The CREATE pipeline persists the deterministic UUID as the remote identity.
        parsed = UUID(value)
        return str(parsed)

    def _select(
        self, attachment: ServiceAttachmentModel
    ) -> tuple[
        PanelInstance,
        AllocationTargetModel,
        ProviderConnectionTestModel,
        str,
        str,
    ]:
        contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
        with self.factory() as db:
            target = db.get(AllocationTargetModel, attachment.allocation_target_id)
            if target is None:
                raise ValueError("allocation target unavailable")
            try:
                inbound_id = int(target.inbound_id)
            except ValueError as exc:
                raise ValueError("allocation inbound invalid") from exc
            if (
                target.status not in {"ACTIVE", "ENABLED"}
                or target.provider_kind != ProviderKind.SANAEI_3X_UI.value
                or target.required_protocol not in {"vless", "vmess"}
                or inbound_id <= 0
            ):
                raise ValueError("allocation target is not activation eligible")

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
        request: ServiceActivationRequestModel,
        service: ServiceModel,
        panel: PanelInstance,
        target: AllocationTargetModel,
        certification: ProviderConnectionTestModel,
        login_name: str,
        login_passphrase: str,
        base_url: str,
        remote_identity: str,
        traffic_bytes: int,
        device_limit: int,
        activation_at: datetime,
        expires_at: datetime,
    ) -> ActivationResult:
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
                return ActivationResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_AUTH_FAILED")
            except ConnectionError:
                return ActivationResult("TRANSIENT_FAILURE", "PROVIDER_AUTH_UNAVAILABLE")

            contract = CERTIFIED_CONTRACTS[ProviderKind.SANAEI_3X_UI]
            inbound = RemoteIdentifier(target.inbound_id)
            provider_label = f"svc-{remote_identity.replace('-', '')[:20]}"
            command = ProviderMutationCommand(
                UUID(request.id),
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
                    RemoteTrafficLimit(traffic_bytes),
                    RemoteExpiryPolicy(expires_at),
                    device_limit,
                    "customer service",
                    provider_label,
                    (inbound,),
                ),
                "PROVISIONED_DISABLED_NO_EXPIRY",
                f"service-activation:v1:{service.id}",
                "activation-worker",
                "activate paid service immediately before customer delivery",
                activation_at,
                request.correlation_id,
                request.causation_id,
            )
            result = await execute_certified_sanaei_activation(
                SanaeiActivationExecutor(transport, panel),
                panel,
                command,
                writes_enabled=True,
                detected_version=certification.detected_version,
                detected_digest=certification.contract_digest,
                certification_status=ProviderCertificationStatus(certification.status),
            )
            if result.outcome is MutationOutcome.SUCCESS:
                return ActivationResult(
                    "SUCCESS",
                    result.safe_code,
                    activation_at,
                    expires_at,
                    result.delivery_links,
                )
            return ActivationResult(result.outcome.value, result.safe_code)
        finally:
            if transport is not None:
                await transport.aclose()
