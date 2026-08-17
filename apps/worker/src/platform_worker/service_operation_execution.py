"""Crash-safe execution of paid additive service operations.

The worker serializes provider mutations per service, persists deterministic targets
before provider I/O, and reconciles retries through the provider executor. Financial
capture happens upstream; definitive execution failures therefore surface as
compensation/manual-review states rather than silently discarding paid work.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from platform_api.order_models import TransactionalOutboxModel
from platform_api.service_models import (
    ServiceAttachmentModel,
    ServiceOperationAttachmentPlanModel,
    ServiceOperationModel,
    ServiceStateRevisionModel,
    ServiceModel,
)
from platform_api.service_operation_payment_models import ServiceOperationPaymentModel

EVENT_TYPE = "service_operation.ready.v1"
LEASE = timedelta(minutes=5)
SERIALIZATION_RETRY = timedelta(seconds=30)
BLOCKED_RETRY = timedelta(hours=6)
MAX_BATCH = 10
MAX_TRANSIENT_ATTEMPTS = 8
MAX_AMBIGUOUS_ATTEMPTS = 12
MAX_BLOCKED_ATTEMPTS = 20
_SUPPORTED_OPERATIONS = frozenset({"RENEW", "ADD_TRAFFIC"})
_ACTIVE_OPERATION_STATES = frozenset({"EXECUTING", "VERIFYING", "RECONCILING"})
_TERMINAL_OPERATION_STATES = frozenset(
    {
        "SUCCEEDED",
        "PARTIALLY_APPLIED",
        "FAILED",
        "UNCERTAIN",
        "COMPENSATION_REQUIRED",
        "COMPENSATED",
        "MANUAL_REVIEW",
        "CANCELLED",
        "EXPIRED",
    }
)


@dataclass(frozen=True)
class ServiceOperationExecutionResult:
    outcome: str
    safe_code: str


class ServiceOperationExecutor(Protocol):
    def execute(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> ServiceOperationExecutionResult: ...


class DisabledServiceOperationExecutor:
    def execute(
        self,
        operation: ServiceOperationModel,
        service: ServiceModel,
        attachment: ServiceAttachmentModel,
        plan: ServiceOperationAttachmentPlanModel,
    ) -> ServiceOperationExecutionResult:
        del operation, service, attachment, plan
        return ServiceOperationExecutionResult(
            "BLOCKED_BY_CONFIGURATION", "PROVIDER_WRITES_DISABLED"
        )


def retry_delay(attempt: int) -> timedelta:
    seconds = min(30 * (2 ** max(attempt - 1, 0)), 3600)
    return timedelta(seconds=seconds)


def _positive_int(snapshot: dict[str, object], key: str) -> int:
    value = snapshot.get(key)
    if type(value) is not int or value <= 0:
        raise ValueError(f"invalid {key}")
    return value


def _aware(value: datetime | None, field: str) -> datetime:
    if value is None or value.tzinfo is None:
        raise ValueError(f"invalid {field}")
    return value


def _desired_state(
    service: ServiceModel, operation: ServiceOperationModel, now: datetime
) -> dict[str, object]:
    entitlement = service.entitlement_snapshot
    current_traffic = _positive_int(entitlement, "traffic_quota_bytes")
    current_expiry = _aware(service.expires_at, "service expiry")
    device_limit = entitlement.get("device_limit")
    if device_limit is not None and (type(device_limit) is not int or device_limit <= 0):
        raise ValueError("invalid device_limit")

    traffic_delta = operation.desired_change.get("traffic_delta_bytes", 0)
    duration_delta = operation.desired_change.get("duration_delta_seconds", 0)
    if type(traffic_delta) is not int or traffic_delta < 0:
        raise ValueError("invalid traffic delta")
    if type(duration_delta) is not int or duration_delta < 0:
        raise ValueError("invalid duration delta")

    if operation.operation_type == "RENEW":
        if duration_delta <= 0 or traffic_delta != 0:
            raise ValueError("invalid renewal desired change")
        baseline_expiry = max(current_expiry, now)
        target_expiry = baseline_expiry + timedelta(seconds=duration_delta)
        target_traffic = current_traffic
    elif operation.operation_type == "ADD_TRAFFIC":
        if traffic_delta <= 0 or duration_delta != 0:
            raise ValueError("invalid traffic desired change")
        target_expiry = current_expiry
        target_traffic = current_traffic + traffic_delta
    else:
        raise ValueError("operation unsupported")

    return {
        "operation_type": operation.operation_type,
        "service_version_base": service.version,
        "traffic_limit_bytes": target_traffic,
        "expires_at": target_expiry.isoformat(),
        "device_limit": cast(int | None, device_limit),
    }


def _target_digest(operation_id: str, attachment_id: str, desired: dict[str, object]) -> str:
    canonical = json.dumps(desired, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(
        f"{operation_id}|{attachment_id}|{canonical}".encode()
    ).hexdigest()


class ServiceOperationExecutionWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        executor: ServiceOperationExecutor,
        worker_id: str,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.factory = factory
        self.executor = executor
        self.worker_id = worker_id
        self.now = now

    def _claim(self) -> list[str]:
        now = self.now()
        with self.factory.begin() as db:
            events = list(
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
            for event in events:
                event.status = "CLAIMED"
                event.claimed_at = now
                event.attempt_count += 1
                event.failure_category = None
            return [event.id for event in events]

    @staticmethod
    def _fail_event(
        event: TransactionalOutboxModel,
        code: str,
        now: datetime,
        *,
        terminal: bool,
        delay: timedelta | None = None,
    ) -> None:
        event.status = "FAILED" if terminal else "PENDING"
        event.failure_category = code
        event.claimed_at = None
        if terminal:
            event.processed_at = now
        else:
            event.available_at = now + (delay or SERIALIZATION_RETRY)

    def _prepare(self, event_id: str) -> tuple[str, tuple[str, ...]] | None:
        now = self.now()
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
            if operation.status in _TERMINAL_OPERATION_STATES:
                self._fail_event(
                    event, f"SERVICE_OPERATION_{operation.status}", now, terminal=True
                )
                return None
            if operation.operation_type not in _SUPPORTED_OPERATIONS:
                operation.status = "MANUAL_REVIEW"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_OPERATION_UNSUPPORTED", now, terminal=True)
                return None
            if operation.status not in {"QUEUED", "EXECUTING", "RECONCILING"}:
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

            service = db.scalar(
                select(ServiceModel)
                .where(ServiceModel.id == operation.service_id)
                .with_for_update()
            )
            if service is None:
                operation.status = "COMPENSATION_REQUIRED"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_MISSING_AFTER_PAYMENT", now, terminal=True)
                return None

            other_active = db.scalar(
                select(ServiceOperationModel.id)
                .where(
                    ServiceOperationModel.service_id == service.id,
                    ServiceOperationModel.id != operation.id,
                    ServiceOperationModel.status.in_(_ACTIVE_OPERATION_STATES),
                )
                .limit(1)
            )
            if other_active is not None:
                self._fail_event(
                    event,
                    "SERVICE_OPERATION_SERIALIZED",
                    now,
                    terminal=False,
                    delay=SERIALIZATION_RETRY,
                )
                return None

            plans = list(
                db.scalars(
                    select(ServiceOperationAttachmentPlanModel).where(
                        ServiceOperationAttachmentPlanModel.operation_id == operation.id
                    )
                )
            )
            if not plans:
                try:
                    desired = _desired_state(service, operation, now)
                except ValueError:
                    operation.status = "COMPENSATION_REQUIRED"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event, "SERVICE_OPERATION_TARGET_INVALID", now, terminal=True
                    )
                    return None
                attachments = list(
                    db.scalars(
                        select(ServiceAttachmentModel)
                        .where(
                            ServiceAttachmentModel.service_id == service.id,
                            ServiceAttachmentModel.required.is_(True),
                        )
                        .order_by(ServiceAttachmentModel.id)
                    )
                )
                if not attachments or any(
                    not attachment.remote_identity_reference for attachment in attachments
                ):
                    operation.status = "COMPENSATION_REQUIRED"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event, "SERVICE_OPERATION_ATTACHMENTS_UNAVAILABLE", now, terminal=True
                    )
                    return None
                for attachment in attachments:
                    plan = ServiceOperationAttachmentPlanModel(
                        operation_id=operation.id,
                        attachment_id=attachment.id,
                        required=attachment.required,
                        provider_operation_id=str(
                            uuid5(
                                NAMESPACE_URL,
                                f"vpnsale:service-operation:{operation.id}:{attachment.id}",
                            )
                        ),
                        capability="ADDITIVE_SERVICE_ADJUSTMENT",
                        expected_snapshot_digest=_target_digest(
                            operation.id, attachment.id, desired
                        ),
                        status="PLANNED",
                        verified=False,
                        uncertain=False,
                        result_snapshot={"desired_state": desired},
                        created_at=now,
                    )
                    db.add(plan)
                    plans.append(plan)
                db.flush()
            operation.status = "EXECUTING"
            operation.updated_at = now
            operation.version += 1
            return operation.id, tuple(plan.id for plan in plans)

    def _load_plan_work(
        self, plan_id: str
    ) -> tuple[
        ServiceOperationModel,
        ServiceModel,
        ServiceAttachmentModel,
        ServiceOperationAttachmentPlanModel,
    ] | None:
        now = self.now()
        with self.factory.begin() as db:
            plan = db.scalar(
                select(ServiceOperationAttachmentPlanModel)
                .where(ServiceOperationAttachmentPlanModel.id == plan_id)
                .with_for_update()
            )
            if plan is None or plan.status == "SUCCEEDED":
                return None
            operation = db.get(ServiceOperationModel, plan.operation_id)
            if operation is None or operation.status not in {
                "EXECUTING",
                "RECONCILING",
            }:
                return None
            service = db.get(ServiceModel, operation.service_id)
            attachment = db.get(ServiceAttachmentModel, plan.attachment_id)
            if service is None or attachment is None:
                plan.status = "FAILED"
                plan.verified = False
                plan.uncertain = False
                plan.result_snapshot = {
                    **plan.result_snapshot,
                    "outcome": "PERMANENT_FAILURE",
                    "safe_code": "SERVICE_OR_ATTACHMENT_MISSING",
                }
                return None
            plan.status = "EXECUTING"
            plan.verified = False
            operation.status = "EXECUTING"
            operation.updated_at = now
            db.flush()
            for row in (operation, service, attachment, plan):
                db.expunge(row)
            return operation, service, attachment, plan

    def _record_plan_result(
        self, plan_id: str, result: ServiceOperationExecutionResult
    ) -> None:
        now = self.now()
        with self.factory.begin() as db:
            plan = db.scalar(
                select(ServiceOperationAttachmentPlanModel)
                .where(ServiceOperationAttachmentPlanModel.id == plan_id)
                .with_for_update()
            )
            if plan is None:
                return
            snapshot = {
                **plan.result_snapshot,
                "outcome": result.outcome,
                "safe_code": result.safe_code,
                "observed_at": now.isoformat(),
            }
            plan.result_snapshot = snapshot
            if result.outcome == "SUCCESS":
                plan.status = "SUCCEEDED"
                plan.verified = True
                plan.uncertain = False
            elif result.outcome == "AMBIGUOUS":
                plan.status = "RECONCILING"
                plan.verified = False
                plan.uncertain = True
            elif result.outcome == "TRANSIENT_FAILURE":
                plan.status = "READY"
                plan.verified = False
                plan.uncertain = False
            elif result.outcome in {
                "BLOCKED_BY_CONFIGURATION",
                "REQUIRES_RECERTIFICATION",
                "CONTRACT_MISMATCH",
            }:
                plan.status = "BLOCKED"
                plan.verified = False
                plan.uncertain = False
            else:
                plan.status = "FAILED"
                plan.verified = False
                plan.uncertain = False

    @staticmethod
    def _desired_from_plan(plan: ServiceOperationAttachmentPlanModel) -> dict[str, object]:
        raw = plan.result_snapshot.get("desired_state")
        if not isinstance(raw, dict):
            raise ValueError("desired state missing")
        return cast(dict[str, object], raw)

    def _complete_success(
        self,
        db: Session,
        event: TransactionalOutboxModel,
        operation: ServiceOperationModel,
        service: ServiceModel,
        plans: list[ServiceOperationAttachmentPlanModel],
        now: datetime,
    ) -> None:
        desired = self._desired_from_plan(plans[0])
        if any(self._desired_from_plan(plan) != desired for plan in plans[1:]):
            operation.status = "MANUAL_REVIEW"
            operation.updated_at = now
            operation.version += 1
            self._fail_event(event, "SERVICE_OPERATION_TARGET_DIVERGED", now, terminal=True)
            return
        traffic = desired.get("traffic_limit_bytes")
        expires_raw = desired.get("expires_at")
        if type(traffic) is not int or traffic <= 0 or not isinstance(expires_raw, str):
            operation.status = "MANUAL_REVIEW"
            operation.updated_at = now
            operation.version += 1
            self._fail_event(event, "SERVICE_OPERATION_TARGET_INVALID", now, terminal=True)
            return
        try:
            expires_at = datetime.fromisoformat(expires_raw)
        except ValueError:
            operation.status = "MANUAL_REVIEW"
            operation.updated_at = now
            operation.version += 1
            self._fail_event(event, "SERVICE_OPERATION_TARGET_INVALID", now, terminal=True)
            return
        if expires_at.tzinfo is None:
            operation.status = "MANUAL_REVIEW"
            operation.updated_at = now
            operation.version += 1
            self._fail_event(event, "SERVICE_OPERATION_TARGET_INVALID", now, terminal=True)
            return

        previous = db.scalar(
            select(ServiceStateRevisionModel)
            .where(ServiceStateRevisionModel.service_id == service.id)
            .order_by(ServiceStateRevisionModel.revision_number.desc())
            .limit(1)
        )
        revision_number = (previous.revision_number + 1) if previous else 1
        entitlement = dict(service.entitlement_snapshot)
        entitlement["traffic_quota_bytes"] = traffic
        service.entitlement_snapshot = entitlement
        service.expires_at = expires_at
        if service.lifecycle == "EXPIRED" and expires_at > now:
            service.lifecycle = "ACTIVE"
        service.version += 1
        db.add(
            ServiceStateRevisionModel(
                service_id=service.id,
                operation_id=operation.id,
                revision_number=revision_number,
                desired_state={
                    **desired,
                    "service_lifecycle": service.lifecycle,
                    "applied_service_version": service.version,
                },
                previous_revision_id=previous.id if previous else None,
                created_at=now,
            )
        )
        operation.status = "SUCCEEDED"
        operation.updated_at = now
        operation.version += 1
        event.status = "PROCESSED"
        event.processed_at = now
        event.claimed_at = None
        event.failure_category = None

    def _settle(self, event_id: str, operation_id: str) -> None:
        now = self.now()
        with self.factory.begin() as db:
            event = db.scalar(
                select(TransactionalOutboxModel)
                .where(TransactionalOutboxModel.id == event_id)
                .with_for_update()
            )
            operation = db.scalar(
                select(ServiceOperationModel)
                .where(ServiceOperationModel.id == operation_id)
                .with_for_update()
            )
            if event is None or operation is None:
                return
            service = db.scalar(
                select(ServiceModel)
                .where(ServiceModel.id == operation.service_id)
                .with_for_update()
            )
            if service is None:
                operation.status = "COMPENSATION_REQUIRED"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_MISSING_AFTER_EXECUTION", now, terminal=True)
                return
            plans = list(
                db.scalars(
                    select(ServiceOperationAttachmentPlanModel)
                    .where(ServiceOperationAttachmentPlanModel.operation_id == operation.id)
                    .order_by(ServiceOperationAttachmentPlanModel.id)
                )
            )
            if not plans:
                operation.status = "COMPENSATION_REQUIRED"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(event, "SERVICE_OPERATION_PLAN_MISSING", now, terminal=True)
                return
            required = [plan for plan in plans if plan.required]
            if required and all(plan.status == "SUCCEEDED" and plan.verified for plan in required):
                self._complete_success(db, event, operation, service, plans, now)
                return

            succeeded = [plan for plan in required if plan.status == "SUCCEEDED" and plan.verified]
            uncertain = [plan for plan in required if plan.status == "RECONCILING" or plan.uncertain]
            blocked = [plan for plan in required if plan.status == "BLOCKED"]
            failed = [plan for plan in required if plan.status == "FAILED"]
            transient = [plan for plan in required if plan.status in {"PLANNED", "READY", "EXECUTING"}]

            if uncertain:
                if event.attempt_count >= MAX_AMBIGUOUS_ATTEMPTS:
                    operation.status = "UNCERTAIN"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event, "SERVICE_OPERATION_UNCERTAIN_RETRY_EXHAUSTED", now, terminal=True
                    )
                else:
                    operation.status = "RECONCILING"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event,
                        "SERVICE_OPERATION_RECONCILIATION_REQUIRED",
                        now,
                        terminal=False,
                        delay=retry_delay(event.attempt_count),
                    )
                return
            if failed:
                operation.status = "PARTIALLY_APPLIED" if succeeded else "COMPENSATION_REQUIRED"
                operation.updated_at = now
                operation.version += 1
                self._fail_event(
                    event,
                    "SERVICE_OPERATION_PARTIAL_FAILURE"
                    if succeeded
                    else "SERVICE_OPERATION_DEFINITIVE_FAILURE",
                    now,
                    terminal=True,
                )
                return
            if blocked:
                if event.attempt_count >= MAX_BLOCKED_ATTEMPTS:
                    operation.status = "MANUAL_REVIEW"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event, "SERVICE_OPERATION_BLOCKED_RETRY_EXHAUSTED", now, terminal=True
                    )
                else:
                    operation.status = "RECONCILING"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event,
                        "SERVICE_OPERATION_PROVIDER_BLOCKED",
                        now,
                        terminal=False,
                        delay=BLOCKED_RETRY,
                    )
                return
            if transient:
                if event.attempt_count >= MAX_TRANSIENT_ATTEMPTS:
                    operation.status = "MANUAL_REVIEW"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event, "SERVICE_OPERATION_TRANSIENT_RETRY_EXHAUSTED", now, terminal=True
                    )
                else:
                    operation.status = "RECONCILING"
                    operation.updated_at = now
                    operation.version += 1
                    self._fail_event(
                        event,
                        "SERVICE_OPERATION_TRANSIENT_FAILURE",
                        now,
                        terminal=False,
                        delay=retry_delay(event.attempt_count),
                    )
                return
            operation.status = "MANUAL_REVIEW"
            operation.updated_at = now
            operation.version += 1
            self._fail_event(event, "SERVICE_OPERATION_UNCLASSIFIED", now, terminal=True)

    def run_once(self) -> int:
        processed = 0
        for event_id in self._claim():
            prepared = self._prepare(event_id)
            if prepared is None:
                continue
            operation_id, plan_ids = prepared
            for plan_id in plan_ids:
                work = self._load_plan_work(plan_id)
                if work is None:
                    continue
                operation, service, attachment, plan = work
                result = self.executor.execute(operation, service, attachment, plan)
                self._record_plan_result(plan_id, result)
                if result.outcome != "SUCCESS":
                    break
            self._settle(event_id, operation_id)
            processed += 1
        return processed
