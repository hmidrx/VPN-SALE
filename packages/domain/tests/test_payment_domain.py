from datetime import UTC, datetime

import pytest
from vpnsale_domain.payments import (
    NormalizedPaymentResult,
    PaymentAmount,
    PaymentAttemptStatus,
    PaymentChannel,
    PaymentDomainError,
    PaymentIntentStatus,
    PaymentMethodPolicy,
    PaymentMethodStatus,
    PaymentPurpose,
    ProviderPaymentStatus,
    require_attempt_transition,
    require_intent_transition,
    require_method_available,
    validate_verified_result,
)


def test_payment_amount_requires_integer_rial() -> None:
    with pytest.raises(PaymentDomainError):
        PaymentAmount(10.5)  # type: ignore[arg-type]
    assert PaymentAmount(10_000).currency == "IRR"


def test_method_policy_and_status_fail_closed() -> None:
    policy = PaymentMethodPolicy(
        10_000,
        100_000,
        frozenset({PaymentPurpose.WALLET_TOPUP}),
        frozenset({PaymentChannel.REDIRECT}),
    )
    policy.validate(PaymentPurpose.WALLET_TOPUP, PaymentChannel.REDIRECT, PaymentAmount(50_000))
    with pytest.raises(PaymentDomainError) as exc:
        require_method_available(PaymentMethodStatus.PAUSED, False)
    assert exc.value.code == "PAYMENT_METHOD_UNAVAILABLE"
    with pytest.raises(PaymentDomainError) as exc:
        policy.validate(
            PaymentPurpose.ORDER_PAYMENT, PaymentChannel.REDIRECT, PaymentAmount(50_000)
        )
    assert exc.value.code == "PAYMENT_PURPOSE_UNSUPPORTED"


def test_state_machines_reject_terminal_backwards_transition() -> None:
    require_intent_transition(PaymentIntentStatus.CREATED, PaymentIntentStatus.REQUIRES_PROVIDER)
    require_attempt_transition(
        PaymentAttemptStatus.CREATED, PaymentAttemptStatus.PROVIDER_REQUESTED
    )
    with pytest.raises(PaymentDomainError):
        require_intent_transition(PaymentIntentStatus.SUCCEEDED, PaymentIntentStatus.PROCESSING)
    with pytest.raises(PaymentDomainError):
        require_attempt_transition(
            PaymentAttemptStatus.VERIFIED_SUCCESS, PaymentAttemptStatus.UNKNOWN
        )


def test_verified_result_requires_exact_amount_currency_and_success() -> None:
    result = NormalizedPaymentResult(
        "ptr_1",
        ProviderPaymentStatus.SUCCEEDED,
        PaymentAmount(1000),
        datetime.now(UTC),
        refundable_amount_rial=1000,
    )
    validate_verified_result(PaymentAmount(1000), result)
    with pytest.raises(PaymentDomainError) as exc:
        validate_verified_result(PaymentAmount(2000), result)
    assert exc.value.code == "PAYMENT_AMOUNT_MISMATCH"


def test_refund_eligibility_requires_trusted_full_refundable_order():
    from vpnsale_domain.payments import (
        PaymentPurpose,
        RefundEligibilityInput,
        calculate_refund_eligibility,
    )

    eligible = calculate_refund_eligibility(
        RefundEligibilityInput(
            100_000, "IRR", 0, True, True, PaymentPurpose.ORDER_PAYMENT, order_refundable=True
        )
    )
    assert eligible.eligible is True
    assert eligible.amount is not None and eligible.amount.amount_rial == 100_000

    duplicate = calculate_refund_eligibility(
        RefundEligibilityInput(
            100_000, "IRR", 1, True, True, PaymentPurpose.ORDER_PAYMENT, order_refundable=True
        )
    )
    assert duplicate.reason_code == "REFUND_ALREADY_EXISTS"


def test_wallet_topup_refund_requires_unreserved_cash_bucket_coverage():
    from vpnsale_domain.payments import (
        PaymentPurpose,
        RefundEligibilityInput,
        calculate_refund_eligibility,
    )

    unsafe = calculate_refund_eligibility(
        RefundEligibilityInput(
            100_000,
            "IRR",
            0,
            True,
            True,
            PaymentPurpose.WALLET_TOPUP,
            wallet_cash_available_rial=120_000,
            wallet_cash_reserved_rial=30_000,
            wallet_cash_credit_from_topup_rial=100_000,
        )
    )
    assert unsafe.eligible is False
    assert unsafe.reason_code == "INSUFFICIENT_UNRESERVED_CASH_COVERAGE"


def test_refund_approval_separation_and_provider_verification():
    from vpnsale_domain.payments import (
        PaymentAmount,
        PaymentDomainError,
        require_creator_approver_separation,
        validate_refund_provider_result,
    )

    with pytest.raises(PaymentDomainError) as exc:
        require_creator_approver_separation("admin-a", "admin-a")
    assert exc.value.code == "REFUND_SELF_APPROVAL_DENIED"
    validate_refund_provider_result(
        PaymentAmount(10_000), "tx1", PaymentAmount(10_000), "SUCCEEDED", "tx1"
    )
    with pytest.raises(PaymentDomainError) as mismatch:
        validate_refund_provider_result(
            PaymentAmount(10_000), "tx1", PaymentAmount(9_000), "SUCCEEDED", "tx1"
        )
    assert mismatch.value.code == "REFUND_AMOUNT_MISMATCH"


def test_reconciliation_mismatch_repair_boundaries_are_stable():
    from vpnsale_domain.payments import (
        ReconciliationScope,
        ReconciliationSeverity,
        RepairEligibility,
        make_mismatch,
    )

    safe = make_mismatch(
        "DERIVED_PAYMENT_STATUS_STALE",
        ReconciliationScope.PAYMENT_INTENT,
        ReconciliationSeverity.WARNING,
        {"settlement": "present"},
        {"status": "PROCESSING"},
        {"status": "SUCCEEDED"},
    )
    critical = make_mismatch(
        "DUPLICATE_SETTLEMENT",
        ReconciliationScope.PAYMENT_SETTLEMENT,
        ReconciliationSeverity.CRITICAL,
        {"count": 2},
        {},
        {},
    )
    assert safe.repair == RepairEligibility.SAFE_DERIVED_STATE
    assert safe.manual_review_required is False
    assert critical.repair == RepairEligibility.BLOCKED_CRITICAL
    assert critical.manual_review_required is True
