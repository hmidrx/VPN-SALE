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


def test_card_number_normalization_and_formatting() -> None:
    from vpnsale_domain.manual_topups import format_card_number, normalize_card_number

    synthetic = "۱۲۳۴-٥٦٧٨ 9012-3456"
    assert normalize_card_number(synthetic) == "1234567890123456"
    assert format_card_number(synthetic) == "1234 5678 9012 3456"


def test_card_number_rejects_malformed_values() -> None:
    import pytest
    from vpnsale_domain.manual_topups import normalize_card_number

    for value in ("1" * 16, "1234/5678/9012/3456", "123456789012345"):
        with pytest.raises(ValueError):
            normalize_card_number(value)
