"""Crash-safe service activation with delivery-profile gating."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.delivery import DeliveryError

from platform_api.activation_models import ServiceActivationRequestModel
from platform_api.delivery_models import DeliveryRevisionModel
from platform_api.delivery_resolution import (
    RENDERER_VERSION,
    load_allocation_delivery_profile,
    render_service_connection,
)
from platform_api.fulfillment_runtime_models import FulfillmentEntitlementClockModel
from platform_api.service_models import (
    AllocationTargetModel,
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
    delivery_profile_version_id: str | None = None
    credential_fingerprint: str | None = None


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


def retry_delay(attempt: int) -> timedelta:
    seconds = min(15 * (2 ** max(attempt - 1, 0)), 3600)
    return timedelta(seconds=seconds)


class ServiceActivationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        activator: ServiceActivator,
        worker_id: str,
    ) -> None:
        self.factory = factory
        self.activator = activator
        self.worker_id = worker_id

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
    def _operator_review(request: ServiceActivationRequestModel, code: str, now: datetime) -> None:
        request.status = "OPERATOR_REVIEW"
        request.failure_category = code
        request.result_code = code
        request.next_attempt_at = None
        request.lease_owner = None
        request.lease_expires_at = None
        request.updated_at = now

    @classmethod
    def _retry_delivery_drift(
        cls,
        request: ServiceActivationRequestModel,
        code: str,
        now: datetime,
    ) -> None:
        if request.attempt_count >= MAX_TRANSIENT_ATTEMPTS:
            cls._operator_review(request, "DELIVERY_DRIFT_RETRY_EXHAUSTED", now)
            return
        request.status = "RETRY_PENDING"
        request.failure_category = "DELIVERY_PRECONDITION_DRIFT"
        request.result_code = code
        request.next_attempt_at = now + retry_delay(request.attempt_count)
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
            revision = db.scalar(
                select(DeliveryRevisionModel)
                .where(
                    DeliveryRevisionModel.service_id == service.id,
                    DeliveryRevisionModel.status == "ACTIVE",
                )
                .order_by(DeliveryRevisionModel.revision_number.desc())
                .limit(1)
            )
            if service.lifecycle == "ACTIVE":
                if revision is not None:
                    request.status = "SUCCEEDED"
                    request.failure_category = None
                    request.result_code = "ALREADY_ACTIVE_AND_DELIVERABLE"
                    request.completed_at = now
                    request.lease_owner = None
                    request.lease_expires_at = None
                    request.updated_at = now
                    db.commit()
                    return None
                self._operator_review(request, "ACTIVE_WITHOUT_DELIVERY_REVISION", now)
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
            db.expunge(request)
            db.expunge(service)
            db.expunge(attachment)
            return request, service, attachment

    def _complete_success(self, request_id: str, result: ActivationResult) -> None:
        if (
            result.activation_at is None
            or result.expires_at is None
            or result.delivery_profile_version_id is None
            or result.credential_fingerprint is None
        ):
            raise ValueError("successful activation must include clock and delivery metadata")
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
            target = db.get(AllocationTargetModel, attachment.allocation_target_id)
            if target is None:
                self._operator_review(request, "ALLOCATION_TARGET_MISSING", now)
                db.commit()
                return
            try:
                profile = load_allocation_delivery_profile(db, target.id, target.required_protocol)
                rendered_uri, fingerprint = render_service_connection(
                    service,
                    attachment,
                    target,
                    profile,
                    require_verified=True,
                )
            except (DeliveryError, ValueError):
                self._retry_delivery_drift(request, "DELIVERY_PROFILE_CHANGED_OR_INVALID", now)
                db.commit()
                return
            if (
                str(profile.version_id) != result.delivery_profile_version_id
                or fingerprint != result.credential_fingerprint
                or not rendered_uri
            ):
                self._retry_delivery_drift(request, "DELIVERY_PRECONDITION_CHANGED", now)
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

            latest_number = db.scalar(
                select(func.max(DeliveryRevisionModel.revision_number)).where(
                    DeliveryRevisionModel.service_id == service.id
                )
            )
            revision_number = int(latest_number or 0) + 1
            db.add(
                DeliveryRevisionModel(
                    service_id=service.id,
                    revision_number=revision_number,
                    status="ACTIVE",
                    attachment_snapshot={
                        "attachment_id": attachment.id,
                        "allocation_target_id": target.id,
                        "profile_version_id": str(profile.version_id),
                        "protocol": profile.protocol.value,
                        "transport": profile.transport.value,
                        "security": profile.security.value,
                    },
                    renderer_versions={"URI": RENDERER_VERSION},
                    credential_fingerprints={attachment.id: fingerprint},
                    compatibility_state={
                        "direct_uri": True,
                        "provider_host_used": False,
                    },
                    reason="ACTIVATION_VERIFIED",
                    correlation_reference=request.correlation_id,
                    created_at=now,
                    superseded_at=None,
                )
            )
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
            attachment.credential_fingerprint = fingerprint
            observed = dict(attachment.observed_state or {})
            observed.update(
                {
                    "provider_verified": True,
                    "delivery_verified": True,
                    "activation_result_code": result.safe_code,
                    "delivery_profile_version_id": str(profile.version_id),
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
                self._complete_success(request_id, result)
            else:
                self._complete_failure(request_id, result)
            processed += 1
        return processed
