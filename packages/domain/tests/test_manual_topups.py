import pytest
from vpnsale_domain.manual_topups import (
    ManualTopupStatus,
    approval_amounts,
    customer_safe_text,
    require_transition,
    validate_requested_amount,
)


def test_state_machine_and_terminal_states() -> None:
    require_transition(ManualTopupStatus.AWAITING_RECEIPT, ManualTopupStatus.UNDER_REVIEW)
    require_transition(ManualTopupStatus.UNDER_REVIEW, ManualTopupStatus.APPROVED)
    with pytest.raises(ValueError):
        require_transition(ManualTopupStatus.APPROVED, ManualTopupStatus.UNDER_REVIEW)


def test_amounts_remain_exact_and_distinct() -> None:
    assert validate_requested_amount(1_000_000, 2_000_000) == 1_000_000
    assert approval_amounts(1_000_000, 500_000) == (1_000_000, 500_000, 1_500_000)


def test_customer_message_rejects_destination_like_digit_sequence() -> None:
    with pytest.raises(ValueError):
        customer_safe_text("شماره ۶۰۳۷ ۹۹۱۱ ۱۲۲۲ ۳۳۳۳")
