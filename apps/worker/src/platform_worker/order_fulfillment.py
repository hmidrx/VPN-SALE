"""Lease-based order fulfillment orchestration.

The database claim is committed before provider I/O. A persisted remote UUID and
read-before-create provider contract close all response-loss crash windows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from vpnsale_domain.services import canonical_service_entitlement

from platform_api.delivery_models import DeliverySubscriptionModel
from platform_api.order_models import OrderItemModel, OrderModel, TransactionalOutboxModel
from platform_api.orders import compensate_failed_fulfillment
from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceFulfillmentRequestModel,
    ServiceModel,
)

EVENT_TYPE = "order.ready_for_fulfillment.v1"
LEASE = timedelta(minutes=5)
BLOCKED_RETRY = timedelta(hours=6)
MAX_BATCH = 10
MAX_TRANSIENT_ATTEMPTS = 8
MAX_AMBIGUOUS_ATTEMPTS = 12
MAX_BLOCKED_ATTEMPTS = 20


@dataclass(frozen=True)
class ProvisioningResult:
    outcome: str
    safe_code: str
    expires_at: datetime | None = None
    provider_mapping: dict[str, object] | None = None
    delivery_ready: bool = False
    remote_identity_reference: str | None = None


class ProviderProvisioner(Protocol):
    def provision(
        self, attempt: ServiceFulfillmentRequestModel, order: OrderModel, item: OrderItemModel
    ) -> ProvisioningResult: ...


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * (2 ** min(max(attempt - 1, 0), 7))))


class DisabledProvisioner:
    def provision(
        self, attempt: ServiceFulfillmentRequestModel, order: OrderModel, item: OrderItemModel
    ) -> ProvisioningResult:
        return ProvisioningResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")


class OrderFulfillmentWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        provisioner: ProviderProvisioner,
        owner: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.factory = factory
        self.provisioner = provisioner
        self.owner = owner
        self.now = now

    def _claim(self) -> list[str]:
        now = self.now()
        with self.factory.begin() as db:
            rows = list(
                db.scalars(
                    select(TransactionalOutboxModel)
                    .where(
                        TransactionalOutboxModel.event_type == EVENT_TYPE,
                        TransactionalOutboxModel.available_at <= now,
                        (TransactionalOutboxModel.status == "PENDING")
                        | (
                            (TransactionalOutboxModel.status == "CLAIMED")
                            & (TransactionalOutboxModel.claimed_at < now - LEASE)
                        ),
                    )
                    .order_by(TransactionalOutboxModel.created_at)
                    .limit(MAX_BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            for row in rows:
                row.status = "CLAIMED"
                row.claimed_at = now
                row.attempt_count += 1
            return [row.id for row in rows]

    def _prepare(self, event_id: str) -> tuple[str, str, str] | None:
        now = self.now()
        with self.factory.begin() as db:
            event = db.get(TransactionalOutboxModel, event_id)
            if not event or event.status != "CLAIMED":
                return None
            order_id = event.payload.get("order_id")
            if not isinstance(order_id, str):
                self._fail_event(event, "ORDER_SNAPSHOT_INVALID", now, terminal=True)
                return None
            order = db.scalar(select(OrderModel).where(OrderModel.id == order_id).with_for_update())
            item = db.scalar(select(OrderItemModel).where(OrderItemModel.order_id == order_id))
            if not order or not item or order.status != "READY_FOR_FULFILLMENT":
                self._fail_event(event, "ORDER_NOT_FULFILLABLE", now, terminal=True)
                return None
            attempt = db.scalar(
                select(ServiceFulfillmentRequestModel)
                .where(ServiceFulfillmentRequestModel.order_item_id == item.id)
                .with_for_update()
            )
            if not attempt:
                identity = str(uuid5(NAMESPACE_URL, f"vpnsale:fulfillment:{order.id}:{item.id}:1"))
                attempt = ServiceFulfillmentRequestModel(
                    deduplication_key=f"order:{order.id}:item:{item.id}:unit:1",
                    order_id=order.id,
                    order_item_id=item.id,
                    unit_index=1,
                    event_version=1,
                    status="IN_PROGRESS",
                    correlation_id=str(event.payload.get("correlation_id", event.id)),
                    causation_id=event.id,
                    lease_owner=self.owner,
                    lease_expires_at=now + LEASE,
                    remote_identity_uuid=identity,
                    attempt_count=1,
                    created_at=now,
                    updated_at=now,
                )
                db.add(attempt)
                db.flush()
            elif attempt.status == "SUCCEEDED":
                event.status = "PROCESSED"
                event.processed_at = now
                return None
            else:
                attempt.status = "IN_PROGRESS"
                attempt.lease_owner = self.owner
                attempt.lease_expires_at = now + LEASE
                attempt.attempt_count += 1
                attempt.updated_at = now
            order.fulfillment_status = "PROVISIONING"
            return attempt.id, order.id, item.id

    @staticmethod
    def _fail_event(
        event: TransactionalOutboxModel, code: str, now: datetime, *, terminal: bool
    ) -> None:
        event.status = "FAILED" if terminal else "PENDING"
        event.failure_category = code
        event.claimed_at = None
        if not terminal:
            event.available_at = now + BLOCKED_RETRY

    def _finish(self, event_id: str, attempt_id: str, result: ProvisioningResult) -> None:
        now = self.now()
        with self.factory.begin() as db:
            event = db.get(TransactionalOutboxModel, event_id)
            attempt = db.get(ServiceFulfillmentRequestModel, attempt_id)
            if not event or not attempt or attempt.status == "SUCCEEDED":
                if event and attempt and attempt.status == "SUCCEEDED":
                    event.status, event.processed_at = "PROCESSED", now
                return
            order = db.get(OrderModel, attempt.order_id)
            item = db.get(OrderItemModel, attempt.order_item_id)
            if order is None or item is None:
                self._fail_event(event, "ORDER_SNAPSHOT_INVALID", now, terminal=True)
                attempt.status = "FAILED"
                attempt.failure_category = "ORDER_SNAPSHOT_INVALID"
                return
            if result.outcome == "SUCCESS":
                entitlement = canonical_service_entitlement(
                    {
                        **item.snapshot,
                        "telegram_purchase_display": order.snapshot.get(
                            "telegram_purchase_display"
                        ),
                    }
                )
                target_id = (result.provider_mapping or {}).get("allocation_target_id")
                if result.delivery_ready and not isinstance(target_id, str):
                    result = ProvisioningResult("CONTRACT_MISMATCH", "DELIVERY_TARGET_MISSING")
                else:
                    self._complete_success(
                        db, event, attempt, order, item, result, entitlement, now
                    )
                    return
            if result.outcome == "PERMANENT_FAILURE":
                compensate_failed_fulfillment(
                    db, order, attempt.correlation_id, "PROVIDER_PROVISIONING_REJECTED"
                )
                attempt.status = "FAILED"
                attempt.failure_category = result.outcome
                attempt.result_code = result.safe_code
                event.status = "FAILED"
                event.processed_at = now
                event.failure_category = result.outcome
            else:
                blocked = result.outcome in {
                    "BLOCKED_BY_CONFIGURATION",
                    "REQUIRES_RECERTIFICATION",
                    "CONTRACT_MISMATCH",
                }
                if blocked:
                    ceiling = MAX_BLOCKED_ATTEMPTS
                elif result.outcome == "AMBIGUOUS":
                    ceiling = MAX_AMBIGUOUS_ATTEMPTS
                else:
                    ceiling = MAX_TRANSIENT_ATTEMPTS
                exhausted = attempt.attempt_count >= ceiling
                attempt.status = (
                    "OPERATOR_REVIEW" if exhausted else ("BLOCKED" if blocked else "RETRY_PENDING")
                )
                attempt.failure_category = result.outcome
                attempt.result_code = result.safe_code
                if exhausted:
                    order.fulfillment_status = "OPERATOR_REVIEW"
                    event.status = "FAILED"
                    event.processed_at = now
                    event.failure_category = "RETRY_EXHAUSTED"
                    attempt.next_attempt_at = None
                else:
                    delay = BLOCKED_RETRY if blocked else retry_delay(attempt.attempt_count)
                    attempt.next_attempt_at = now + delay
                    event.status = "PENDING"
                    event.claimed_at = None
                    event.failure_category = result.outcome
                    event.available_at = now + delay
            attempt.lease_owner = None
            attempt.lease_expires_at = None
            attempt.updated_at = now

    def _complete_success(
        self,
        db: Session,
        event: TransactionalOutboxModel,
        attempt: ServiceFulfillmentRequestModel,
        order: OrderModel,
        item: OrderItemModel,
        result: ProvisioningResult,
        entitlement: dict[str, object],
        now: datetime,
    ) -> None:
        service = db.scalar(
            select(ServiceModel).where(
                ServiceModel.order_item_id == item.id, ServiceModel.unit_index == 1
            )
        )
        if not service:
            service_reference = uuid5(NAMESPACE_URL, "service:" + order.id).hex[:24]
            service = ServiceModel(
                public_reference=f"svc_{service_reference}",
                lifecycle="ACTIVE" if result.delivery_ready else "PENDING_ACTIVATION",
                beneficiary_customer_id=order.customer_id,
                payer_type="CUSTOMER",
                payer_reference=order.customer_id,
                order_id=order.id,
                order_item_id=item.id,
                unit_index=1,
                entitlement_snapshot=entitlement,
                allocation_policy_snapshot=result.provider_mapping or {},
                starts_at=now if result.delivery_ready else None,
                expires_at=result.expires_at if result.delivery_ready else None,
                activated_at=now if result.delivery_ready else None,
                created_at=now,
            )
            db.add(service)
            db.flush()
        if result.delivery_ready:
            mapping = result.provider_mapping or {}
            target_id = mapping["allocation_target_id"]
            attachment = db.scalar(
                select(ServiceAttachmentModel).where(
                    ServiceAttachmentModel.service_id == service.id,
                    ServiceAttachmentModel.allocation_target_id == target_id,
                )
            )
            if attachment is None:
                db.add(
                    ServiceAttachmentModel(
                        service_id=service.id,
                        allocation_target_id=target_id,
                        required=True,
                        status="VERIFIED",
                        verification_status="VERIFIED",
                        provider_operation_id=attempt.id,
                        remote_identity_reference=result.remote_identity_reference,
                        credential_fingerprint=None,
                        target_snapshot={"delivery_ready": True},
                        observed_state={"verified": True},
                        last_reconciled_at=now,
                    )
                )
            subscription = db.scalar(
                select(DeliverySubscriptionModel).where(
                    DeliverySubscriptionModel.service_id == service.id,
                    DeliverySubscriptionModel.scope == "SERVICE",
                )
            )
            if subscription is None:
                subscription_reference = uuid5(NAMESPACE_URL, "subscription:" + service.id).hex[:24]
                db.add(
                    DeliverySubscriptionModel(
                        public_reference=f"sub_{subscription_reference}",
                        service_id=service.id,
                        scope="SERVICE",
                        status="READY_FOR_TOKEN_ISSUANCE",
                        active_token_hash=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
        attempt.service_id = service.id
        attempt.status = "SUCCEEDED"
        attempt.result_code = result.safe_code
        order.fulfillment_status = "SUCCEEDED"
        event.status, event.processed_at = "PROCESSED", now
        event.failure_category = None
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        attempt.updated_at = now

    def run_once(self) -> int:
        processed = 0
        for event_id in self._claim():
            prepared = self._prepare(event_id)
            if not prepared:
                continue
            attempt_id, order_id, item_id = prepared
            with self.factory() as db:
                attempt = db.get(ServiceFulfillmentRequestModel, attempt_id)
                order = db.get(OrderModel, order_id)
                item = db.get(OrderItemModel, item_id)
                if attempt is None or order is None or item is None:
                    continue
                result = self.provisioner.provision(attempt, order, item)
            self._finish(event_id, attempt_id, result)
            processed += 1
        return processed
