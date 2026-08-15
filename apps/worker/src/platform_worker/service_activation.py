"""Durable post-provisioning activation with fail-closed customer delivery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform_api.activation_models import ServiceActivationRequestModel
from platform_api.delivery_models import DeliveryRevisionModel
from platform_api.fulfillment_runtime_models import FulfillmentEntitlementClockModel
from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceFulfillmentRequestModel,
    ServiceModel,
)
from platform_worker.real_activator import ActivationProviderResult, DatabaseSanaeiActivator

LEASE = timedelta(minutes=5)
BLOCKED_RETRY = timedelta(hours=6)
MAX_TRANSIENT_ATTEMPTS = 8
MAX_AMBIGUOUS_ATTEMPTS = 12
MAX_BLOCKED_ATTEMPTS = 20
BATCH_SIZE = 10


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(30 * (2 ** max(attempt - 1, 0)), 3600))


class ServiceActivationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        activator: DatabaseSanaeiActivator,
        lease_owner: str,
    ) -> None:
        self.factory = factory
        self.activator = activator
        self.lease_owner = lease_owner

    def _seed_requests(self) -> None:
        now = datetime.now(UTC)
        with self.factory.begin() as db:
            candidates = list(
                db.execute(
                    select(ServiceModel.id, ServiceFulfillmentRequestModel.id)
                    .join(
                        ServiceFulfillmentRequestModel,
                        ServiceFulfillmentRequestModel.service_id == ServiceModel.id,
                    )
                    .outerjoin(
                        ServiceActivationRequestModel,
                        ServiceActivationRequestModel.service_id == ServiceModel.id,
                    )
                    .where(
                        ServiceModel.lifecycle == "PENDING_ACTIVATION",
                        ServiceFulfillmentRequestModel.status == "SUCCEEDED",
                        ServiceActivationRequestModel.id.is_(None),
                    )
                    .order_by(ServiceModel.created_at)
                    .limit(100)
                )
            )
            for service_id, fulfillment_id in candidates:
                try:
                    with db.begin_nested():
                        db.add(
                            ServiceActivationRequestModel(
                                id=str(uuid4()),
                                service_id=service_id,
                                fulfillment_request_id=fulfillment_id,
                                status="PENDING",
                                attempt_count=0,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        db.flush()
                except IntegrityError:
                    # Another worker/process won the unique service/request race.
                    continue

    def _claim(self) -> list[str]:
        now = datetime.now(UTC)
        claimed: list[str] = []
        with self.factory.begin() as db:
            rows = list(
                db.scalars(
                    select(ServiceActivationRequestModel)
                    .where(
                        ServiceActivationRequestModel.status.in_(
                            {"PENDING", "RETRY_PENDING", "BLOCKED", "PROCESSING"}
                        ),
                        or_(
                            ServiceActivationRequestModel.next_attempt_at.is_(None),
                            ServiceActivationRequestModel.next_attempt_at <= now,
                        ),
                        or_(
                            ServiceActivationRequestModel.lease_expires_at.is_(None),
                            ServiceActivationRequestModel.lease_expires_at <= now,
                        ),
                    )
                    .order_by(ServiceActivationRequestModel.created_at)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.status = "PROCESSING"
                row.attempt_count += 1
                row.lease_owner = self.lease_owner
                row.lease_expires_at = now + LEASE
                row.updated_at = now
                claimed.append(row.id)
        return claimed

    @staticmethod
    def _reset_unconsumed_clock(
        db: Session,
        activation: ServiceActivationRequestModel,
        service: ServiceModel,
    ) -> None:
        """Restore full paid duration only when the provider definitively did not activate."""
        if activation.activation_instant is None and activation.expires_at is None:
            return
        clock = db.get(FulfillmentEntitlementClockModel, activation.fulfillment_request_id)
        if clock is not None:
            db.delete(clock)
        staged = list(
            db.scalars(
                select(DeliveryRevisionModel).where(
                    DeliveryRevisionModel.service_id == service.id,
                    DeliveryRevisionModel.status == "STAGED",
                )
            )
        )
        for revision in staged:
            db.delete(revision)
        activation.activation_instant = None
        activation.expires_at = None

    def _finish(self, activation_id: str, result: ActivationProviderResult) -> None:
        now = datetime.now(UTC)
        with self.factory.begin() as db:
            activation = db.scalar(
                select(ServiceActivationRequestModel)
                .where(ServiceActivationRequestModel.id == activation_id)
                .with_for_update()
            )
            if activation is None:
                return
            if activation.status == "SUCCEEDED":
                return
            service = db.get(ServiceModel, activation.service_id)
            if service is None:
                activation.status = "OPERATOR_REVIEW"
                activation.failure_category = "LOCAL_SERVICE_MISSING"
                activation.result_code = "LOCAL_SERVICE_MISSING"
                activation.lease_owner = None
                activation.lease_expires_at = None
                activation.updated_at = now
                return

            if result.outcome == "SUCCESS":
                if activation.activation_instant is None or activation.expires_at is None:
                    raise ValueError("successful provider activation requires durable entitlement clock")
                attachment = db.scalar(
                    select(ServiceAttachmentModel).where(
                        ServiceAttachmentModel.service_id == service.id,
                        ServiceAttachmentModel.required.is_(True),
                    )
                )
                revision = db.scalar(
                    select(DeliveryRevisionModel)
                    .where(
                        DeliveryRevisionModel.service_id == service.id,
                        DeliveryRevisionModel.status == "STAGED",
                    )
                    .order_by(DeliveryRevisionModel.revision_number.desc())
                    .limit(1)
                    .with_for_update()
                )
                if (
                    attachment is None
                    or revision is None
                    or not revision.encrypted_payload
                    or not revision.encryption_key_version
                    or not revision.payload_sha256
                ):
                    raise ValueError("successful activation requires staged encrypted delivery")

                older = list(
                    db.scalars(
                        select(DeliveryRevisionModel).where(
                            DeliveryRevisionModel.service_id == service.id,
                            DeliveryRevisionModel.status == "ACTIVE",
                            DeliveryRevisionModel.id != revision.id,
                        )
                    )
                )
                for item in older:
                    item.status = "SUPERSEDED"
                    item.superseded_at = now
                revision.status = "ACTIVE"
                attachment.status = "VERIFIED"
                attachment.verification_status = "VERIFIED"
                attachment.observed_state = {
                    "provider_verified": True,
                    "activation_verified": True,
                    "delivery_verified": True,
                }
                attachment.last_reconciled_at = now
                service.lifecycle = "ACTIVE"
                service.starts_at = activation.activation_instant
                service.activated_at = activation.activation_instant
                service.expires_at = activation.expires_at
                activation.status = "SUCCEEDED"
                activation.result_code = result.safe_code
                activation.failure_category = None
                activation.next_attempt_at = None
            else:
                blocked = result.outcome in {
                    "BLOCKED_BY_CONFIGURATION",
                    "REQUIRES_RECERTIFICATION",
                    "CONTRACT_MISMATCH",
                }
                definitive_non_activation = result.outcome in {
                    "PERMANENT_FAILURE",
                    "BLOCKED_BY_CONFIGURATION",
                    "REQUIRES_RECERTIFICATION",
                    "CONTRACT_MISMATCH",
                }
                if definitive_non_activation:
                    self._reset_unconsumed_clock(db, activation, service)
                if blocked:
                    ceiling = MAX_BLOCKED_ATTEMPTS
                elif result.outcome == "AMBIGUOUS":
                    ceiling = MAX_AMBIGUOUS_ATTEMPTS
                else:
                    ceiling = MAX_TRANSIENT_ATTEMPTS
                permanent = result.outcome == "PERMANENT_FAILURE"
                exhausted = activation.attempt_count >= ceiling
                if permanent or exhausted:
                    activation.status = "OPERATOR_REVIEW"
                    activation.next_attempt_at = None
                else:
                    activation.status = "BLOCKED" if blocked else "RETRY_PENDING"
                    delay = BLOCKED_RETRY if blocked else retry_delay(activation.attempt_count)
                    activation.next_attempt_at = now + delay
                activation.failure_category = result.outcome
                activation.result_code = result.safe_code

            activation.lease_owner = None
            activation.lease_expires_at = None
            activation.updated_at = now

    def run_once(self) -> int:
        self._seed_requests()
        processed = 0
        for activation_id in self._claim():
            result = self.activator.activate(activation_id)
            self._finish(activation_id, result)
            processed += 1
        return processed
