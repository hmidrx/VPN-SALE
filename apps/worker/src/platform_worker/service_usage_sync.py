"""Read-only provider usage synchronization for customer-safe service projections."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from panel_adapters.contracts import EndpointValidator
from panel_adapters.sanaei_3x_ui_v370 import (
    HttpxSanaei3xUiV370Transport,
    Sanaei3xUiV370ClientRecord,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.providers import (
    ProviderError,
    ProviderKind,
)
from vpnsale_domain.usage import (
    CERTIFIED_COUNTER_SEMANTICS,
    AggregationPolicyVersion,
    AggregationStrategy,
    ObservationConfidence,
    QuotaState,
    ThresholdPolicy,
    UsageAllowance,
    UsageObservation,
    aggregate_usage,
    calculate_remaining,
    evaluate_expiry,
    evaluate_quota,
)

from platform_api.service_models import ServiceAttachmentModel, ServiceModel
from platform_api.usage_models import (
    ServiceUsageAccountModel,
    ServiceUsageAggregateModel,
    ServiceUsageCycleModel,
    ServiceUsageObservationModel,
    ServiceUsageSyncRunModel,
)
from platform_worker.provider_v370_connection import connect_v370
from platform_worker.real_activator import DatabaseSanaeiActivator

_SYNC_INTERVAL = timedelta(minutes=5)
_MAX_BATCH = 20
_POLICY_ID = UUID("6d100000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class SafeUsageProjection:
    used_bytes: int | None
    remaining_bytes: int | None
    overage_bytes: int
    consumed_percent: int | None
    quota_state: str
    expiry_state: str
    confidence: str
    explanation_code: str


def build_safe_usage_projection(
    *,
    service_id: str,
    attachment_id: str,
    allowance_bytes: int,
    combined_bytes: int | None,
    previous_combined_bytes: int | None,
    observed_at: datetime,
    expires_at: datetime | None,
) -> SafeUsageProjection:
    """Project one certified attachment without inventing data after counter anomalies."""
    if combined_bytes is None:
        return SafeUsageProjection(
            None,
            None,
            0,
            None,
            QuotaState.UNKNOWN.value,
            "ACTIVE",
            ObservationConfidence.LOW.value,
            "COUNTER_UNAVAILABLE",
        )
    if previous_combined_bytes is not None and combined_bytes < previous_combined_bytes:
        return SafeUsageProjection(
            None,
            None,
            0,
            None,
            QuotaState.MANUAL_REVIEW.value,
            "ACTIVE",
            ObservationConfidence.UNUSABLE.value,
            "COUNTER_DECREASE_UNEXPLAINED",
        )

    observation = UsageObservation(
        uuid4(),
        UUID(service_id),
        UUID(attachment_id),
        ProviderKind.SANAEI_3X_UI,
        CERTIFIED_COUNTER_SEMANTICS[ProviderKind.SANAEI_3X_UI].contract_code,
        observed_at,
        f"{attachment_id}:inbound-client",
        combined_bytes,
        confidence=ObservationConfidence.HIGH,
        primary=True,
    )
    aggregate = aggregate_usage(
        [observation],
        AggregationPolicyVersion(_POLICY_ID, 1, AggregationStrategy.SINGLE_ATTACHMENT),
        observed_at,
    )
    remaining = calculate_remaining(UsageAllowance(allowance_bytes), aggregate.used_bytes)
    confirmed = (
        2
        if previous_combined_bytes is not None
        and previous_combined_bytes >= allowance_bytes
        and combined_bytes >= allowance_bytes
        else 1
    )
    threshold = ThresholdPolicy(_POLICY_ID, 1)
    quota = evaluate_quota(remaining, aggregate, threshold, 2, confirmed)
    expiry = evaluate_expiry(expires_at, observed_at, threshold, timedelta(0), 1, 1)
    return SafeUsageProjection(
        aggregate.used_bytes,
        remaining.remaining_bytes,
        remaining.overage_bytes,
        remaining.consumed_percent,
        quota.value,
        expiry.value,
        aggregate.confidence.value,
        aggregate.explanation_code,
    )


class ServiceUsageSyncWorker:
    """Persist fresh certified provider counters independently from the provider-write gate."""

    def __init__(self, factory: sessionmaker[Session], worker_id: str) -> None:
        self.factory = factory
        self.worker_id = worker_id[:80]
        # The activator's resolver enforces the same credential, endpoint and certification policy.
        # writes_enabled is intentionally false: this worker performs provider reads only.
        self.resolver = DatabaseSanaeiActivator(factory, writes_enabled=False)

    @staticmethod
    def _allowance(service: ServiceModel) -> int | None:
        value = service.entitlement_snapshot.get("traffic_quota_bytes")
        return value if type(value) is int and value > 0 else None

    def _due(self, db: Session, service: ServiceModel, now: datetime) -> bool:
        account = db.scalar(
            select(ServiceUsageAccountModel).where(
                ServiceUsageAccountModel.service_id == service.id
            )
        )
        if account is None:
            return True
        latest = db.scalar(
            select(ServiceUsageAggregateModel)
            .where(ServiceUsageAggregateModel.usage_account_id == account.id)
            .order_by(ServiceUsageAggregateModel.calculated_at.desc())
            .limit(1)
        )
        return latest is None or now - latest.calculated_at >= _SYNC_INTERVAL

    def _candidates(
        self, db: Session, now: datetime
    ) -> list[tuple[ServiceModel, ServiceAttachmentModel]]:
        services = db.scalars(
            select(ServiceModel)
            .where(ServiceModel.lifecycle == "ACTIVE")
            .order_by(ServiceModel.created_at)
            .limit(_MAX_BATCH * 3)
        ).all()
        candidates: list[tuple[ServiceModel, ServiceAttachmentModel]] = []
        for service in services:
            if self._allowance(service) is None or not self._due(db, service, now):
                continue
            attachments = db.scalars(
                select(ServiceAttachmentModel).where(
                    ServiceAttachmentModel.service_id == service.id,
                    ServiceAttachmentModel.required.is_(True),
                    ServiceAttachmentModel.verification_status == "VERIFIED",
                    ServiceAttachmentModel.remote_identity_reference.is_not(None),
                )
            ).all()
            # Current bot products use one authoritative attachment. Multi-attachment aggregation
            # remains fail-closed until a published aggregation policy identifies dedupe semantics.
            if len(attachments) != 1:
                continue
            candidates.append((service, attachments[0]))
            if len(candidates) >= _MAX_BATCH:
                break
        return candidates

    async def _fetch_client(
        self, attachment: ServiceAttachmentModel
    ) -> tuple[Sanaei3xUiV370ClientRecord, str]:
        panel, target, _, credential = self.resolver.provider_read_context(attachment)
        endpoint_origin = EndpointValidator().validate(
            panel.endpoint_origin,
            panel.endpoint_policy,
            panel.tls_policy,
        )
        transport: HttpxSanaei3xUiV370Transport | None = None
        try:
            transport, client = await connect_v370(
                panel,
                endpoint_origin,
                credential,
            )
            remote_identity = str(UUID(attachment.remote_identity_reference or ""))
            provider_label = f"svc-{remote_identity.replace('-', '')[:20]}"
            record = await client.read_client(provider_label)
            record_identity = record.client.get("id", record.client.get("uuid"))
            if (
                record_identity is not None
                and str(record_identity) != remote_identity
                or int(target.inbound_id) not in record.inbound_ids
            ):
                raise ValueError("authoritative provider usage identity unavailable")
            return record, "0.7.0"
        finally:
            if transport is not None:
                await transport.aclose()

    @staticmethod
    def _counter(client: Sanaei3xUiV370ClientRecord) -> int | None:
        return client.used_traffic_bytes

    def _account_cycle(
        self,
        db: Session,
        service: ServiceModel,
        allowance: int,
        now: datetime,
    ) -> tuple[ServiceUsageAccountModel, ServiceUsageCycleModel]:
        account = db.scalar(
            select(ServiceUsageAccountModel)
            .where(ServiceUsageAccountModel.service_id == service.id)
            .with_for_update()
        )
        if account is None:
            account = ServiceUsageAccountModel(
                service_id=service.id,
                allowance_bytes=allowance,
                is_unlimited=False,
                aggregation_policy_version=1,
                lifetime_baseline_bytes=0,
                version=1,
                created_at=now,
            )
            db.add(account)
            db.flush()
        elif account.allowance_bytes != allowance or account.is_unlimited:
            account.allowance_bytes = allowance
            account.is_unlimited = False
            account.version += 1

        cycle = db.scalar(
            select(ServiceUsageCycleModel)
            .where(
                ServiceUsageCycleModel.usage_account_id == account.id,
                ServiceUsageCycleModel.status == "ACTIVE",
            )
            .order_by(ServiceUsageCycleModel.started_at.desc())
            .limit(1)
            .with_for_update()
        )
        allowance_snapshot: dict[str, object] = {
            "finite_bytes": allowance,
            "unlimited": False,
            "source": "service_entitlement",
        }
        if cycle is None:
            cycle = ServiceUsageCycleModel(
                usage_account_id=account.id,
                cycle_kind="SERVICE_LIFETIME",
                status="ACTIVE",
                start_reason="SERVICE_ACTIVATED",
                started_at=service.activated_at or service.starts_at or service.created_at,
                ended_at=None,
                allowance_snapshot=allowance_snapshot,
                lifetime_baseline_bytes=0,
                aggregation_policy_version=1,
                service_operation_id=None,
                version=1,
            )
            db.add(cycle)
            db.flush()
        elif cycle.allowance_snapshot != allowance_snapshot:
            cycle.allowance_snapshot = allowance_snapshot
            cycle.version += 1
        return account, cycle

    def _persist(
        self,
        service_id: str,
        attachment_id: str,
        client: Sanaei3xUiV370ClientRecord,
        adapter_version: str,
        observed_at: datetime,
    ) -> bool:
        with self.factory() as db:
            service = db.get(ServiceModel, service_id)
            attachment = db.get(ServiceAttachmentModel, attachment_id)
            if service is None or attachment is None or service.lifecycle != "ACTIVE":
                return False
            allowance = self._allowance(service)
            if allowance is None:
                return False
            account, cycle = self._account_cycle(db, service, allowance, observed_at)
            previous = db.scalar(
                select(ServiceUsageObservationModel)
                .where(ServiceUsageObservationModel.attachment_id == attachment.id)
                .order_by(ServiceUsageObservationModel.observed_at.desc())
                .limit(1)
            )
            combined = self._counter(client)
            projection = build_safe_usage_projection(
                service_id=service.id,
                attachment_id=attachment.id,
                allowance_bytes=allowance,
                combined_bytes=combined,
                previous_combined_bytes=previous.combined_bytes if previous else None,
                observed_at=observed_at,
                expires_at=service.expires_at,
            )
            if not client.inbound_ids:
                return False
            scope = f"{attachment.id}:{client.inbound_ids[0]}:{client.email}"
            bucket = int(observed_at.timestamp()) // int(_SYNC_INTERVAL.total_seconds())
            idem = hashlib.sha256(f"usage:v1:{attachment.id}:{scope}:{bucket}".encode()).hexdigest()
            if db.scalar(
                select(ServiceUsageObservationModel.id).where(
                    ServiceUsageObservationModel.idempotency_key_hash == idem
                )
            ):
                return False
            anomalies = (
                ["COUNTER_DECREASE_UNEXPLAINED"]
                if projection.explanation_code == "COUNTER_DECREASE_UNEXPLAINED"
                else []
            )
            observation = ServiceUsageObservationModel(
                usage_account_id=account.id,
                service_id=service.id,
                attachment_id=attachment.id,
                counter_generation_id=None,
                provider_kind=ProviderKind.SANAEI_3X_UI.value,
                provider_contract_code=(
                    CERTIFIED_COUNTER_SEMANTICS[ProviderKind.SANAEI_3X_UI].contract_code
                ),
                adapter_version=adapter_version,
                observed_at=observed_at,
                counter_scope_key=scope,
                upload_bytes=None,
                download_bytes=None,
                combined_bytes=combined,
                remote_limit_bytes=client.total_bytes,
                remote_expiry_at=(
                    datetime.fromtimestamp(client.expiry_time_ms / 1000, tz=UTC)
                    if client.expiry_time_ms > 0
                    else None
                ),
                remote_enabled=(
                    client.client.get("enable")
                    if type(client.client.get("enable")) is bool
                    else None
                ),
                online_state=None,
                confidence=projection.confidence,
                anomaly_flags=anomalies,
                idempotency_key_hash=idem,
            )
            db.add(observation)
            db.add(
                ServiceUsageAggregateModel(
                    usage_account_id=account.id,
                    cycle_id=cycle.id,
                    used_bytes=projection.used_bytes,
                    remaining_bytes=projection.remaining_bytes,
                    overage_bytes=projection.overage_bytes,
                    consumed_percent=projection.consumed_percent,
                    quota_state=projection.quota_state,
                    expiry_state=projection.expiry_state,
                    confidence=projection.confidence,
                    calculated_at=observed_at,
                    latest_observed_at=observed_at,
                    explanation_code=projection.explanation_code,
                    version=1,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return False
        return True

    def _record_run(
        self, started: datetime, status: str, processed: int, failures: int, finished: datetime
    ) -> None:
        with self.factory() as db:
            db.add(
                ServiceUsageSyncRunModel(
                    worker_name=self.worker_id,
                    status=status,
                    started_at=started,
                    finished_at=finished,
                    safe_summary={"processed": processed, "failures": failures},
                )
            )
            db.commit()

    def run_once(self) -> int:
        started = datetime.now(UTC)
        with self.factory() as db:
            candidates = self._candidates(db, started)
        if not candidates:
            return 0

        processed = 0
        failures = 0
        for service, attachment in candidates:
            try:
                client, adapter_version = asyncio.run(self._fetch_client(attachment))
                if self._persist(
                    service.id,
                    attachment.id,
                    client,
                    adapter_version,
                    datetime.now(UTC),
                ):
                    processed += 1
            except (
                ProviderError,
                PermissionError,
                ConnectionError,
                TimeoutError,
                ValueError,
                httpx.HTTPError,
            ):
                failures += 1
        finished = datetime.now(UTC)
        self._record_run(
            started,
            "SUCCESS" if failures == 0 else "PARTIAL" if processed else "FAILED",
            processed,
            failures,
            finished,
        )
        return processed
