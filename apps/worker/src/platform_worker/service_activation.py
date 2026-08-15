"""Crash-safe service activation and encrypted customer delivery persistence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform_api.activation_models import ServiceActivationRequestModel, ServiceDeliveryModel
from platform_api.fulfillment_runtime_models import FulfillmentEntitlementClockModel
from platform_api.identity.security import FernetSecretEncryptor
from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceFulfillmentRequestModel,
    ServiceModel,
)

LEASE = timedelta(minutes=5)
BLOCKED_RETRY = timedelta(hours=6)
MAX_BATCH = 10
MAX_TRANSIENT_ATTEMPTS = 8
MAX_AMBIGUOUS_ATTEMPTS = 12
MAX_BLOCKED_ATTEMPTS = 20


@dataclass(frozen=True)
class ActivationResult:
    outcome: str
    safe_code: str
    activation_at: datetime | None = None
    expires_at: datetime | None = None
    delivery_links: tuple[str, ...] = ()


class ServiceActivator(Protocol):
    def activate(
        self,
        request: ServiceActivationRequestModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
    ) -> ActivationResult: ...


class DisabledActivator:
    def activate(
        self,
        request: ServiceActivationRequestModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
    ) -> ActivationResult:
        del request, service, attachment
        return ActivationResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")


class FernetDeliveryCipher:
    """Encrypt provider-generated customer links before any durable persistence."""

    def __init__(self, key: str, key_version: str) -> None:
        self.encryptor = FernetSecretEncryptor(key, key_version)

    def encrypt_links(self, links: tuple[str, ...]) -> tuple[str, str, str]:
        if not links:
            raise ValueError("delivery links required")
        payload = json.dumps(
            {"version": 1, "links": list(links)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(payload.encode()).hexdigest()
        encrypted = self.encryptor.encrypt(payload)
        return encrypted.key_version, encrypted.ciphertext, digest


def retry_delay(attempt: int) -> timedelta:
    seconds = min(15 * (2 ** max(attempt - 1, 0)), 3600)
    return timedelta(seconds=seconds)


class ServiceActivationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        activator: ServiceActivator,
        worker_id: str,
        delivery_cipher: FernetDeliveryCipher | None,
    ) -> None:
        self.factory = factory
        self.activator = activator
        self.worker_id = worker_id
        self.delivery_cipher = delivery_cipher

    def _discover(self) -> int:
        now = datetime.now(UTC)
        created = 0
        with self.factory() as db:
            services = list(
                db.scalars(
                    select(ServiceModel)
                    .outerjoin(
                        ServiceActivationRequestModel,
                        ServiceActivationRequestModel.service_id == ServiceModel.id,
                    )
                    .where(
                        ServiceModel.lifecycle == "PENDING_ACTIVATION",
                        ServiceActivationRequestModel.id.is_(None),
                    )
                    .order_by(ServiceModel.created_at)
                    .limit(MAX_BATCH)
                )
            )
            for service in services:
                attachment = db.scalar(
                    select(ServiceAttachmentModel).where(
                        ServiceAttachmentModel.service_id == service.id,
                        ServiceAttachmentModel.required.is_(True),
                        ServiceAttachmentModel.status == "PROVISIONED",
                        ServiceAttachmentModel.verification_status == "PENDING_DELIVERY",
                    )
                )
                if attachment is None:
                    continue
                try:
                    with db.begin_nested():
                        db.add(
                            ServiceActivationRequestModel(
                                service_id=service.id,
                                status="PENDING",
                                attempt_count=0,
                                correlation_id=f"service-activation:{service.id}",
                                causation_id=f"order-fulfillment:{service.order_id}",
                                created_at=now,
                                updated_at=now,
                            )
                        )
                        db.flush()
                    created += 1
                except IntegrityError:
                    pass
            db.commit()
        return created

    def _claim(self) -> list[str]:
        now = datetime.now(UTC)
        with self.factory() as db:
            rows = list(
                db.scalars(
                    select(ServiceActivationRequestModel)
                    .where(
                        or_(
                            ServiceActivationRequestModel.status.in_(
                                ("PENDING", "RETRY_PENDING", "BLOCKED")
                            ),
                            (
                                (ServiceActivationRequestModel.status == "CLAIMED")
                                & (ServiceActivationRequestModel.lease_expires_at < now)
                            ),
                        ),
                        or_(
                            ServiceActivationRequestModel.next_attempt_at.is_(None),
                            ServiceActivationRequestModel.next_attempt_at <= now,
                        ),
                    )
                    .order_by(ServiceActivationRequestModel.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(MAX_BATCH)
                )
            )
            for row in rows:
                row.status = "CLAIMED"
                row.attempt_count += 1
                row.lease_owner = self.worker_id
                row.lease_expires_at = now + LEASE
                row.next_attempt_at = None
                row.updated_at = now
            db.commit()
            return [row.id for row in rows]

    @staticmethod
    def _operator_review(
        request: ServiceActivationRequestModel, code: str, now: datetime
    ) -> None:
        request.status = "OPERATOR_REVIEW"
        request.failure_category = code
        request.result_code = code
        request.next_attempt_at = None
        request.lease_owner = None
        request.lease_expires_at = None
        request.updated_at = now

    def _load_work(
        self, request_id: str
    ) -> tuple[ServiceActivationRequestModel, ServiceModel, ServiceAttachmentModel] | None:
        now = datetime.now(UTC)
        with self.factory() as db:
            request = db.get(ServiceActivationRequestModel, request_id)
            if (
                request is None
                or request.status != "CLAIMED"
                or request.lease_owner != self.worker_id
            ):
                return None
            service = db.get(ServiceModel, request.service_id)
            if service is None:
                self._operator_review(request, "SERVICE_MISSING", now)
                db.commit()
                return None
            deliveries = list(
                db.scalars(
                    select(ServiceDeliveryModel).where(ServiceDeliveryModel.service_id == service.id)
                )
            )
            if service.lifecycle == "ACTIVE":
                if len(deliveries) == 1 and deliveries[0].status == "DELIVERED":
                    request.status = "SUCCEEDED"
                    request.failure_category = None
                    request.result_code = "ALREADY_ACTIVE_AND_DELIVERED"
                    request.completed_at = now
                    request.lease_owner = None
                    request.lease_expires_at = None
                    request.updated_at = now
                    db.commit()
                    return None
                self._operator_review(request, "ACTIVE_WITHOUT_DELIVERY", now)
                db.commit()
                return None
            if service.lifecycle != "PENDING_ACTIVATION":
                self._operator_review(request, "SERVICE_LIFECYCLE_INVALID", now)
                db.commit()
                return None
            attachments = list(
                db.scalars(
                    select(ServiceAttachmentModel).where(
                        ServiceAttachmentModel.service_id == service.id,
                        ServiceAttachmentModel.required.is_(True),
                    )
                )
            )
            if len(attachments) != 1:
                self._operator_review(request, "REQUIRED_ATTACHMENT_CARDINALITY_INVALID", now)
                db.commit()
                return None
            attachment = attachments[0]
            if (
                attachment.status != "PROVISIONED"
                or attachment.verification_status != "PENDING_DELIVERY"
                or not attachment.remote_identity_reference
            ):
                self._operator_review(request, "ATTACHMENT_NOT_READY_FOR_ACTIVATION", now)
                db.commit()
                return None
            if self.delivery_cipher is None:
                request.status = "BLOCKED"
                request.failure_category = "DELIVERY_ENCRYPTION_UNAVAILABLE"
                request.result_code = "DELIVERY_ENCRYPTION_UNAVAILABLE"
                request.next_attempt_at = now + BLOCKED_RETRY
                request.lease_owner = None
                request.lease_expires_at = None
                request.updated_at = now
                db.commit()
                return None
            db.expunge(request)
            db.expunge(service)
            db.expunge(attachment)
            return request, service, attachment

    def _complete_success(
        self,
        request_id: str,
        result: ActivationResult,
        encrypted: tuple[str, str, str],
    ) -> None:
        if result.activation_at is None or result.expires_at is None or not result.delivery_links:
            raise ValueError("successful activation must include clock and delivery links")
        now = datetime.now(UTC)
        key_version, ciphertext, digest = encrypted
        with self.factory() as db:
            request = db.scalar(
                select(ServiceActivationRequestModel)
                .where(ServiceActivationRequestModel.id == request_id)
                .with_for_update()
            )
            if (
                request is None
                or request.status != "CLAIMED"
                or request.lease_owner != self.worker_id
            ):
                return
            service = db.scalar(
                select(ServiceModel).where(ServiceModel.id == request.service_id).with_for_update()
            )
            if service is None:
                self._operator_review(request, "SERVICE_MISSING", now)
                db.commit()
                return
            attachment = db.scalar(
                select(ServiceAttachmentModel)
                .where(
                    ServiceAttachmentModel.service_id == service.id,
                    ServiceAttachmentModel.required.is_(True),
                )
                .with_for_update()
            )
            if attachment is None:
                self._operator_review(request, "ATTACHMENT_MISSING", now)
                db.commit()
                return
            fulfillment = db.scalar(
                select(ServiceFulfillmentRequestModel).where(
                    ServiceFulfillmentRequestModel.service_id == service.id
                )
            )
            if fulfillment is None:
                self._operator_review(request, "FULFILLMENT_REQUEST_MISSING", now)
                db.commit()
                return
            clock = db.get(FulfillmentEntitlementClockModel, fulfillment.id)
            if clock is not None and (
                clock.starts_at != result.activation_at or clock.expires_at != result.expires_at
            ):
                self._operator_review(request, "ENTITLEMENT_CLOCK_CONFLICT", now)
                db.commit()
                return

            delivery = db.scalar(
                select(ServiceDeliveryModel)
                .where(ServiceDeliveryModel.service_id == service.id)
                .with_for_update()
            )
            if delivery is None:
                delivery = ServiceDeliveryModel(
                    service_id=service.id,
                    format="URI_LIST",
                    encrypted_payload=ciphertext,
                    encryption_key_version=key_version,
                    payload_sha256=digest,
                    item_count=len(result.delivery_links),
                    status="DELIVERED",
                    created_at=now,
                    delivered_at=now,
                )
                db.add(delivery)
            else:
                if delivery.status == "DELIVERED" and delivery.payload_sha256 != digest:
                    self._operator_review(request, "DELIVERY_PAYLOAD_CONFLICT", now)
                    db.commit()
                    return
                delivery.encrypted_payload = ciphertext
                delivery.encryption_key_version = key_version
                delivery.payload_sha256 = digest
                delivery.item_count = len(result.delivery_links)
                delivery.status = "DELIVERED"
                delivery.delivered_at = now

            if clock is None:
                db.add(
                    FulfillmentEntitlementClockModel(
                        fulfillment_request_id=fulfillment.id,
                        starts_at=result.activation_at,
                        expires_at=result.expires_at,
                        created_at=now,
                    )
                )

            service.lifecycle = "ACTIVE"
            service.starts_at = result.activation_at
            service.activated_at = result.activation_at
            service.expires_at = result.expires_at
            service.version += 1
            attachment.status = "VERIFIED"
            attachment.verification_status = "VERIFIED"
            observed = dict(attachment.observed_state or {})
            observed.update(
                {
                    "provider_verified": True,
                    "delivery_verified": True,
                    "activation_result_code": result.safe_code,
                }
            )
            attachment.observed_state = observed
            attachment.last_reconciled_at = now
            attachment.version += 1

            request.status = "SUCCEEDED"
            request.failure_category = None
            request.result_code = result.safe_code
            request.next_attempt_at = None
            request.completed_at = now
            request.lease_owner = None
            request.lease_expires_at = None
            request.updated_at = now
            db.commit()

    def _complete_failure(self, request_id: str, result: ActivationResult) -> None:
        now = datetime.now(UTC)
        with self.factory() as db:
            request = db.scalar(
                select(ServiceActivationRequestModel)
                .where(ServiceActivationRequestModel.id == request_id)
                .with_for_update()
            )
            if (
                request is None
                or request.status != "CLAIMED"
                or request.lease_owner != self.worker_id
            ):
                return
            blocked = result.outcome in {
                "BLOCKED_BY_CONFIGURATION",
                "REQUIRES_RECERTIFICATION",
                "CONTRACT_MISMATCH",
            }
            if result.outcome == "PERMANENT_FAILURE":
                self._operator_review(request, result.safe_code, now)
                db.commit()
                return
            ceiling = (
                MAX_BLOCKED_ATTEMPTS
                if blocked
                else MAX_AMBIGUOUS_ATTEMPTS
                if result.outcome == "AMBIGUOUS"
                else MAX_TRANSIENT_ATTEMPTS
            )
            if request.attempt_count >= ceiling:
                self._operator_review(request, "ACTIVATION_RETRY_EXHAUSTED", now)
                db.commit()
                return
            request.status = "BLOCKED" if blocked else "RETRY_PENDING"
            request.failure_category = result.outcome
            request.result_code = result.safe_code
            request.next_attempt_at = now + (
                BLOCKED_RETRY if blocked else retry_delay(request.attempt_count)
            )
            request.lease_owner = None
            request.lease_expires_at = None
            request.updated_at = now
            db.commit()

    def run_once(self) -> int:
        self._discover()
        processed = 0
        for request_id in self._claim():
            work = self._load_work(request_id)
            if work is None:
                continue
            request, service, attachment = work
            result = self.activator.activate(request, service, attachment)
            if result.outcome == "SUCCESS":
                assert self.delivery_cipher is not None
                try:
                    encrypted = self.delivery_cipher.encrypt_links(result.delivery_links)
                except (ValueError, TypeError):
                    result = ActivationResult(
                        "BLOCKED_BY_CONFIGURATION", "DELIVERY_ENCRYPTION_FAILED"
                    )
                else:
                    self._complete_success(request_id, result, encrypted)
                    processed += 1
                    continue
            self._complete_failure(request_id, result)
            processed += 1
        return processed
