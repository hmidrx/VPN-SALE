"""Crash-safe execution of paid service operations.

The outbox lease commits before provider I/O. Provider adjustments are target-idempotent,
so an expired lease can safely retry and reconcile after a crash or lost response.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceModel,
    ServiceOperationAttachmentPlanModel,
    ServiceOperationModel,
)
from platform_api.service_operation_payment_models import ServiceOperationPaymentModel

EVENT_TYPE = "service_operation.ready.v1"
LEASE = timedelta(minutes=5)
BLOCKED_RETRY = timedelta(hours=6)
MAX_BATCH = 10
MAX_TRANSIENT_ATTEMPTS = 8
MAX_AMBIGUOUS_ATTEMPTS = 12
MAX_BLOCKED_ATTEMPTS = 20
_GIB = 1024**3
_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class AdjustmentResult:
    outcome: str
    safe_code: str


class ServiceOperationAdjuster(Protocol):
    def adjust(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> AdjustmentResult: ...


class DisabledAdjuster:
    def adjust(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> AdjustmentResult:
        del operation, service, attachment, plan
        return AdjustmentResult("BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED")


def retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * (2 ** min(max(attempt - 1, 0), 7))))


def _target_snapshot(
    operation: ServiceOperationModel,
    service: ServiceModel,
    attachment: ServiceAttachmentModel,
) -> dict[str, object]:
    if operation.operation_type == "RENEW":
        renew_days = operation.desired_change.get("renew_days")
        duration = operation.desired_change.get("duration_delta_seconds")
        if (
            type(renew_days) is not int
            or renew_days <= 0
            or type(duration) is not int
            or duration != renew_days * _DAY
            or service.expires_at is None
        ):
            raise ValueError("renew operation snapshot invalid")
        return {
            "kind": "RENEW",
            "base_service_version": service.version,
            "base_attachment_version": attachment.version,
            "base_expiry": service.expires_at.isoformat(),
            "target_expiry": (service.expires_at + timedelta(days=renew_days)).isoformat(),
            "renew_days": renew_days,
        }
    if operation.operation_type == "ADD_TRAFFIC":
        traffic_gib = operation.desired_change.get("traffic_gib")
        traffic_delta = operation.desired_change.get("traffic_delta_bytes")
        base_traffic = service.entitlement_snapshot.get("traffic_quota_bytes")
        if (
            type(traffic_gib) is not int
            or traffic_gib <= 0
            or type(traffic_delta) is not int
            or traffic_delta != traffic_gib * _GIB
            or type(base_traffic) is not int
            or base_traffic <= 0
        ):
            raise ValueError("traffic operation snapshot invalid")
        return {
            "kind": "ADD_TRAFFIC",
            "base_service_version": service.version,
            "base_attachment_version": attachment.version,
            "base_traffic_quota_bytes": base_traffic,
            "target_traffic_quota_bytes": base_traffic + traffic_delta,
            "traffic_delta_bytes": traffic_delta,
        }
    raise ValueError("service operation type unsupported")


def _snapshot_digest(snapshot: dict[str, object]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class ServiceOperationWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        adjuster: ServiceOperationAdjuster,
        worker_id: str,
    ) -> None:
        self.factory = factory
        self.adjuster = adjuster
        self.worker_id = worker_id

    def _claim(self) -> list[str]:
        now = datetime.now(UTC)
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

    @staticmethod
    def _fail_event(
        event: TransactionalOutboxModel, code: str, now: datetime, *, terminal: bool
    ) -> None:
        event.status = "FAILED" if terminal else "PENDING"
        event.failure_category = code
        event.claimed_at = None
        if terminal:
            event.processed_at = now
        else:
            event.available_at = now + BLOCKED_RETRY

    def _prepare(self, event_id: str) -> tuple[str, str, str, str] | None:
        now = datetime.now(UTC)
        with self.factory.begin() as db:
            event = db.get(TransactionalOutboxModel, event_id)
            if event is None or event.status != "CLAIMED":
                return None
            operation_id = event.payload.get("operation_id")
            if not isinstance(operation_id, str):
                self._fail_event(event, "SERVICE_OPERATION_EVENT_INVALID", now, terminal=True)
                return None
            operation = db.scalar(
                select(ServiceOperationModel)
                .where(ServiceOperationModel.id == operation_id)
                .with_for_update()
            )
            if operation is None:
                self._fail_event(event, "SERVICE_OPERATION_MISSING", now, terminal=True)
                return None
            if operation.status == "SUCCEEDED":
                event.status = "PROCESSED"
                event.processed_at = now
                event.claimed_at = None
                event.failure_category = None
                return None
            if operation.status not in {"QUEUED", "EXECUTING", "VERIFYING"}:
                self._fail_event(event, "SERVICE_OPERATION_NOT_EXECUTABLE", now, terminal=True)
                return None

            payment = db.scalar(
                select(ServiceOperationPaymentModel).where(
                    ServiceOperationPaymentModel.operation_id == operation.id,
                    ServiceOperationPaymentModel.status == "CAPTURED",
                )
            )
            if payment is None:
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_OPERATION_PAYMENT_MISSING", now, terminal=True)
                return None

            service = db.get(ServiceModel, operation.service_id)
            if service is None:
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_MISSING", now, terminal=True)
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
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(
                    event, "REQUIRED_ATTACHMENT_CARDINALITY_INVALID", now, terminal=True
                )
                return None
            attachment = attachments[0]
            if (
                attachment.status != "VERIFIED"
                or attachment.verification_status != "VERIFIED"
                or not attachment.remote_identity_reference
            ):
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_ATTACHMENT_NOT_VERIFIED", now, terminal=True)
                return None

            try:
                target = _target_snapshot(operation, service, attachment)
            except ValueError:
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_OPERATION_TARGET_INVALID", now, terminal=True)
                return None
            digest = _snapshot_digest(target)
            candidate_id = operation.id
            candidate = ServiceOperationAttachmentPlanModel(
                id=candidate_id,
                operation_id=operation.id,
                attachment_id=attachment.id,
                required=True,
                provider_operation_id=operation.id,
                capability=(
                    "CLIENT_EXPIRY_UPDATE"
                    if operation.operation_type == "RENEW"
                    else "CLIENT_TRAFFIC_LIMIT_UPDATE"
                ),
                expected_snapshot_digest=digest,
                status="EXECUTING",
                verified=False,
                uncertain=False,
                result_snapshot={"target_state": target, "attempt_count": event.attempt_count},
                created_at=now,
            )
            try:
                with db.begin_nested():
                    db.add(candidate)
                    db.flush()
            except IntegrityError:
                pass
            plan = db.scalar(
                select(ServiceOperationAttachmentPlanModel)
                .where(
                    ServiceOperationAttachmentPlanModel.operation_id == operation.id,
                    ServiceOperationAttachmentPlanModel.attachment_id == attachment.id,
                )
                .with_for_update()
            )
            if plan is None:
                self._fail_event(event, "SERVICE_OPERATION_PLAN_UNAVAILABLE", now, terminal=False)
                return None
            stored_target = plan.result_snapshot.get("target_state")
            if not isinstance(stored_target, dict) or plan.expected_snapshot_digest != _snapshot_digest(
                cast(dict[str, object], stored_target)
            ):
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_OPERATION_PLAN_DRIFT", now, terminal=True)
                return None
            if plan.status == "SUCCEEDED" and plan.verified:
                self._complete_verified(db, event, operation, service, attachment, plan, now)
                return None
            plan.status = "EXECUTING"
            plan.uncertain = False
            result_snapshot = dict(plan.result_snapshot)
            result_snapshot["attempt_count"] = event.attempt_count
            plan.result_snapshot = result_snapshot
            operation.status = "EXECUTING"
            operation.updated_at = now
            operation.version += 1
            return operation.id, service.id, attachment.id, plan.id

    def _load_work(
        self, prepared: tuple[str, str, str, str]
    ) -> tuple[
        ServiceOperationModel,
        ServiceModel,
        ServiceAttachmentModel,
        ServiceOperationAttachmentPlanModel,
    ] | None:
        operation_id, service_id, attachment_id, plan_id = prepared
        with self.factory() as db:
            operation = db.get(ServiceOperationModel, operation_id)
            service = db.get(ServiceModel, service_id)
            attachment = db.get(ServiceAttachmentModel, attachment_id)
            plan = db.get(ServiceOperationAttachmentPlanModel, plan_id)
            if not operation or not service or not attachment or not plan:
                return None
            for row in (operation, service, attachment, plan):
                db.expunge(row)
            return operation, service, attachment, plan

    @staticmethod
    def _complete_verified(
        db: Session,
        event: TransactionalOutboxModel,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
        now: datetime,
    ) -> None:
        target_value = plan.result_snapshot.get("target_state")
        if not isinstance(target_value, dict):
            operation.status = "MANUAL_REVIEW"
            event.status = "FAILED"
            event.failure_category = "SERVICE_OPERATION_TARGET_INVALID"
            event.processed_at = now
            event.claimed_at = None
            return
        target = cast(dict[str, object], target_value)
        kind = target.get("kind")
        if kind == "RENEW":
            base_raw = target.get("base_expiry")
            target_raw = target.get("target_expiry")
            if not isinstance(base_raw, str) or not isinstance(target_raw, str):
                raise ValueError("renew target invalid")
            base_expiry = datetime.fromisoformat(base_raw)
            target_expiry = datetime.fromisoformat(target_raw)
            if service.expires_at != base_expiry:
                operation.status = "MANUAL_REVIEW"
                event.status = "FAILED"
                event.failure_category = "SERVICE_STATE_CHANGED_AFTER_PROVIDER_WRITE"
                event.processed_at = now
                event.claimed_at = None
                return
            service.expires_at = target_expiry
        elif kind == "ADD_TRAFFIC":
            base_traffic = target.get("base_traffic_quota_bytes")
            target_traffic = target.get("target_traffic_quota_bytes")
            current_traffic = service.entitlement_snapshot.get("traffic_quota_bytes")
            if (
                type(base_traffic) is not int
                or type(target_traffic) is not int
                or current_traffic != base_traffic
            ):
                operation.status = "MANUAL_REVIEW"
                event.status = "FAILED"
                event.failure_category = "SERVICE_STATE_CHANGED_AFTER_PROVIDER_WRITE"
                event.processed_at = now
                event.claimed_at = None
                return
            entitlement = dict(service.entitlement_snapshot)
            entitlement["traffic_quota_bytes"] = target_traffic
            service.entitlement_snapshot = entitlement
        else:
            raise ValueError("service operation target kind invalid")

        service.version += 1
        attachment.last_reconciled_at = now
        attachment.version += 1
        operation.status = "SUCCEEDED"
        operation.updated_at = now
        operation.version += 1
        plan.status = "SUCCEEDED"
        plan.verified = True
        plan.uncertain = False
        event.status = "PROCESSED"
        event.processed_at = now
        event.claimed_at = None
        event.failure_category = None

    def _finish(self, event_id: str, plan_id: str, result: AdjustmentResult) -> None:
        now = datetime.now(UTC)
        with self.factory.begin() as db:
            event = db.get(TransactionalOutboxModel, event_id)
            plan = db.scalar(
                select(ServiceOperationAttachmentPlanModel)
                .where(ServiceOperationAttachmentPlanModel.id == plan_id)
                .with_for_update()
            )
            if event is None or plan is None:
                return
            operation = db.scalar(
                select(ServiceOperationModel)
                .where(ServiceOperationModel.id == plan.operation_id)
                .with_for_update()
            )
            if operation is None:
                self._fail_event(event, "SERVICE_OPERATION_MISSING", now, terminal=True)
                return
            service = db.get(ServiceModel, operation.service_id)
            attachment = db.get(ServiceAttachmentModel, plan.attachment_id)
            if service is None or attachment is None:
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_EXECUTION_STATE_MISSING", now, terminal=True)
                return

            snapshot = dict(plan.result_snapshot)
            snapshot["last_outcome"] = result.outcome
            snapshot["last_safe_code"] = result.safe_code
            snapshot["finished_at"] = now.isoformat()
            plan.result_snapshot = snapshot
            if result.outcome == "SUCCESS":
                plan.status = "SUCCEEDED"
                plan.verified = True
                plan.uncertain = False
                self._complete_verified(db, event, operation, service, attachment, plan, now)
                return

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
            terminal = result.outcome == "PERMANENT_FAILURE" or event.attempt_count >= ceiling
            plan.verified = False
            plan.uncertain = result.outcome == "AMBIGUOUS"
            plan.status = "MANUAL_REVIEW" if terminal else (
                "VERIFYING" if result.outcome == "AMBIGUOUS" else "RETRY_PENDING"
            )
            if terminal:
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                event.status = "FAILED"
                event.processed_at = now
                event.claimed_at = None
                event.failure_category = (
                    "SERVICE_OPERATION_RETRY_EXHAUSTED"
                    if result.outcome != "PERMANENT_FAILURE"
                    else result.outcome
                )
                return
            operation.status = "VERIFYING" if result.outcome == "AMBIGUOUS" else "QUEUED"
            operation.updated_at = now
            operation.version += 1
            delay = BLOCKED_RETRY if blocked else retry_delay(event.attempt_count)
            event.status = "PENDING"
            event.claimed_at = None
            event.failure_category = result.outcome
            event.available_at = now + delay

    def run_once(self) -> int:
        processed = 0
        for event_id in self._claim():
            prepared = self._prepare(event_id)
            if prepared is None:
                continue
            work = self._load_work(prepared)
            if work is None:
                with self.factory.begin() as db:
                    event = db.get(TransactionalOutboxModel, event_id)
                    if event is not None:
                        self._fail_event(event, "SERVICE_EXECUTION_LOAD_FAILED", datetime.now(UTC), terminal=False)
                continue
            operation, service, attachment, plan = work
            result = self.adjuster.adjust(operation, service, attachment, plan)
            self._finish(event_id, plan.id, result)
            processed += 1
        return processed
