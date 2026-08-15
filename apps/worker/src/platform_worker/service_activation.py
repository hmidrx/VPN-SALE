"""Lease-based activation, authoritative verification and atomic delivery publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.activation import start_entitlement

from platform_api.activation_models import ServiceActivationAttemptModel, ServiceDeliveryRecordModel
from platform_api.fulfillment_runtime_models import FulfillmentEntitlementClockModel
from platform_api.service_models import ServiceAttachmentModel, ServiceModel

LEASE = timedelta(minutes=5)
MAX_BATCH = 10


@dataclass(frozen=True)
class ActivationResult:
    outcome: str
    safe_code: str
    activated_at: datetime | None = None
    configuration: str | None = None


class ServiceActivator(Protocol):
    def activate(
        self, service: ServiceModel, attachment: ServiceAttachmentModel
    ) -> ActivationResult: ...


class PayloadEncryptor(Protocol):
    @property
    def key_version(self) -> str: ...

    def encrypt(self, plaintext: str) -> str: ...


class ActivationWorker:
    """Claim each service once; provider implementations must reconcile before every write."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        activator: ServiceActivator,
        encryptor: PayloadEncryptor,
        owner: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.factory, self.activator, self.encryptor = factory, activator, encryptor
        self.owner, self.now = owner, now

    def _claim(self) -> list[str]:
        now = self.now()
        claimed: list[str] = []
        with self.factory.begin() as db:
            services = list(
                db.scalars(
                    select(ServiceModel)
                    .outerjoin(
                        ServiceActivationAttemptModel,
                        ServiceActivationAttemptModel.service_id == ServiceModel.id,
                    )
                    .where(
                        ServiceModel.lifecycle.in_(("PENDING_ACTIVATION", "ACTIVATING")),
                        or_(
                            ServiceActivationAttemptModel.id.is_(None),
                            ServiceActivationAttemptModel.activation_status == "RETRY_PENDING",
                            (ServiceActivationAttemptModel.activation_status == "ACTIVATING")
                            & (ServiceActivationAttemptModel.lease_expires_at < now),
                        ),
                        or_(
                            ServiceActivationAttemptModel.next_retry_at.is_(None),
                            ServiceActivationAttemptModel.next_retry_at <= now,
                        ),
                    )
                    .order_by(ServiceModel.created_at)
                    .limit(MAX_BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            for service in services:
                attempt = db.scalar(
                    select(ServiceActivationAttemptModel)
                    .where(ServiceActivationAttemptModel.service_id == service.id)
                    .with_for_update()
                )
                if attempt is None:
                    attempt = ServiceActivationAttemptModel(
                        id=str(uuid4()),
                        service_id=service.id,
                        activation_attempt_id=str(
                            uuid5(NAMESPACE_URL, f"vpnsale:activation:{service.id}:1")
                        ),
                        activation_count=0,
                        activation_status="PENDING",
                        created_at=now,
                        updated_at=now,
                    )
                    try:
                        with db.begin_nested():
                            db.add(attempt)
                            db.flush()
                    except IntegrityError:
                        continue
                attempt.activation_count += 1
                attempt.activation_status = "ACTIVATING"
                attempt.lease_owner = self.owner
                attempt.lease_expires_at = now + LEASE
                attempt.next_retry_at = None
                attempt.updated_at = now
                service.lifecycle = "ACTIVATING"
                claimed.append(attempt.id)
        return claimed

    def _finish(self, attempt_id: str, result: ActivationResult) -> None:
        now = self.now()
        with self.factory.begin() as db:
            attempt = db.get(ServiceActivationAttemptModel, attempt_id)
            if attempt is None or attempt.activation_status == "SUCCEEDED":
                return
            service = db.get(ServiceModel, attempt.service_id)
            if service is None:
                return
            if (
                result.outcome == "SUCCESS"
                and result.activated_at is not None
                and result.configuration
            ):
                duration = service.entitlement_snapshot.get("duration_days")
                if type(duration) is int:
                    clock = start_entitlement(result.activated_at, duration)
                    payload = self.encryptor.encrypt(result.configuration)
                    delivery = ServiceDeliveryRecordModel(
                        id=str(uuid4()),
                        service_id=service.id,
                        delivery_ready=True,
                        delivered_at=now,
                        delivery_payload_reference="delivery_" + uuid4().hex,
                        encrypted_payload=payload,
                        encryption_key_version=self.encryptor.key_version,
                        created_at=now,
                    )
                    db.add(delivery)
                    fulfillment_id = db.scalar(
                        select(ServiceAttachmentModel.provider_operation_id).where(
                            ServiceAttachmentModel.service_id == service.id
                        )
                    )
                    if fulfillment_id is None:
                        raise ValueError("activation requires fulfillment identity")
                    db.add(
                        FulfillmentEntitlementClockModel(
                            fulfillment_request_id=fulfillment_id,
                            starts_at=clock.starts_at,
                            expires_at=clock.expires_at,
                            created_at=now,
                        )
                    )
                    service.starts_at = clock.starts_at
                    service.activated_at = clock.activated_at
                    service.expires_at = clock.expires_at
                    service.lifecycle = "ACTIVE"
                    attempt.activation_status = "SUCCEEDED"
                    attempt.activated_at = clock.activated_at
                    attempt.activation_failure_category = None
                    attempt.lease_owner = attempt.lease_expires_at = None
                    attempt.updated_at = now
                    return
                result = ActivationResult("PERMANENT_FAILURE", "ENTITLEMENT_INVALID")
            attempt.activation_status = (
                "FAILED" if result.outcome == "PERMANENT_FAILURE" else "RETRY_PENDING"
            )
            attempt.activation_failure_category = result.safe_code
            attempt.next_retry_at = (
                None
                if attempt.activation_status == "FAILED"
                else now + timedelta(seconds=min(3600, 30 * 2 ** min(attempt.activation_count, 7)))
            )
            attempt.lease_owner = attempt.lease_expires_at = None
            attempt.updated_at = now
            service.lifecycle = (
                "FAILED" if attempt.activation_status == "FAILED" else "PENDING_ACTIVATION"
            )

    def run_once(self) -> int:
        count = 0
        for attempt_id in self._claim():
            with self.factory() as db:
                attempt = db.get(ServiceActivationAttemptModel, attempt_id)
                service = db.get(ServiceModel, attempt.service_id) if attempt else None
                attachment = (
                    db.scalar(
                        select(ServiceAttachmentModel).where(
                            ServiceAttachmentModel.service_id == service.id
                        )
                    )
                    if service
                    else None
                )
                if service is None or attachment is None:
                    result = ActivationResult("PERMANENT_FAILURE", "ACTIVATION_MAPPING_MISSING")
                else:
                    result = self.activator.activate(service, attachment)
            self._finish(attempt_id, result)
            count += 1
        return count
