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
