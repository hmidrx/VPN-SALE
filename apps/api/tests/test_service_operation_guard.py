from __future__ import annotations

from inspect import getsource

from platform_api.service_operation_guard import (
    SERVICE_OPERATION_BLOCKING_STATES,
    SERVICE_OPERATION_IN_FLIGHT_STATES,
    SERVICE_OPERATION_UNRESOLVED_STATES,
    ServiceOperationBlocker,
    blocker_http_detail,
    blocker_reason_for_status,
    find_service_operation_blocker,
)
from platform_api.telegram_service_management_internal import (
    create_service_operation_quote,
    service_management_eligibility,
)
from platform_api.telegram_service_operation_payment_internal import pay_service_operation


def test_only_paid_inflight_and_unresolved_states_block_new_customer_work() -> None:
    assert SERVICE_OPERATION_IN_FLIGHT_STATES == {
        "PENDING_APPROVAL",
        "QUEUED",
        "EXECUTING",
        "VERIFYING",
        "RECONCILING",
    }
    assert SERVICE_OPERATION_UNRESOLVED_STATES == {
        "PARTIALLY_APPLIED",
        "UNCERTAIN",
        "COMPENSATION_REQUIRED",
        "MANUAL_REVIEW",
    }
    assert SERVICE_OPERATION_BLOCKING_STATES == (
        SERVICE_OPERATION_IN_FLIGHT_STATES | SERVICE_OPERATION_UNRESOLVED_STATES
    )
    assert "AWAITING_PAYMENT" not in SERVICE_OPERATION_BLOCKING_STATES
    assert "SUCCEEDED" not in SERVICE_OPERATION_BLOCKING_STATES
    assert "COMPENSATED" not in SERVICE_OPERATION_BLOCKING_STATES


def test_blocker_reason_prefers_customer_safe_progress_and_review_codes() -> None:
    assert blocker_reason_for_status("QUEUED") == "SERVICE_OPERATION_IN_PROGRESS"
    assert blocker_reason_for_status("EXECUTING") == "SERVICE_OPERATION_IN_PROGRESS"
    assert blocker_reason_for_status("UNCERTAIN") == "SERVICE_OPERATION_REVIEW_REQUIRED"
    assert blocker_reason_for_status("MANUAL_REVIEW") == "SERVICE_OPERATION_REVIEW_REQUIRED"
    assert blocker_reason_for_status("SUCCEEDED") is None

    assert (
        blocker_http_detail(
            ServiceOperationBlocker("op", "QUEUED", "SERVICE_OPERATION_IN_PROGRESS")
        )
        == "service_operation_in_progress"
    )
    assert (
        blocker_http_detail(
            ServiceOperationBlocker(
                "op", "UNCERTAIN", "SERVICE_OPERATION_REVIEW_REQUIRED"
            )
        )
        == "service_operation_review_required"
    )


def test_guard_query_prefers_unresolved_and_can_exclude_current_operation() -> None:
    source = getsource(find_service_operation_blocker)
    unresolved = source.index("SERVICE_OPERATION_UNRESOLVED_STATES")
    inflight = source.index("SERVICE_OPERATION_IN_FLIGHT_STATES")
    assert unresolved < inflight
    assert "exclude_operation_id" in source
    assert "ServiceOperationModel.id != exclude_operation_id" in source


def test_quote_replay_stays_idempotent_but_new_quote_is_blocked_before_pricing() -> None:
    source = getsource(create_service_operation_quote)
    replay = source.index("if existing is not None:")
    blocker = source.index("find_service_operation_blocker")
    pricing = source.index("_published_customer_policy")
    assert replay < blocker < pricing
    assert "blocker_http_detail(blocker)" in source


def test_eligibility_surfaces_same_service_blocker_without_quoting() -> None:
    source = getsource(service_management_eligibility)
    assert "find_service_operation_blocker(db, service.id)" in source
    assert "reason_codes.append(blocker.reason_code)" in source
    assert "if not reason_codes:" in source


def test_payment_serializes_on_service_and_blocks_before_any_wallet_mutation() -> None:
    source = getsource(pay_service_operation)
    service_lock = source.index("select(ServiceModel)")
    blocker = source.index("find_service_operation_blocker")
    wallet = source.index("_ensure_wallet")
    payment_link = source.index("operation.payment_id = payment.id")

    assert service_lock < blocker < wallet < payment_link
    assert ".with_for_update()" in source[service_lock:blocker]
    assert "exclude_operation_id=operation.id" in source
    assert "blocker_http_detail(blocker)" in source
