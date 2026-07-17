from __future__ import annotations

import pytest
from vpnsale_domain.wallet import LedgerPosting, PostingDirection, RialAmount, assert_balanced


def test_rial_amount_rejects_float_zero_and_overflow() -> None:
    with pytest.raises(TypeError):
        RialAmount(1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RialAmount(0)
    with pytest.raises(OverflowError):
        RialAmount(10_000_000_000_000)


def test_balanced_double_entry_accepts_equal_debit_credit() -> None:
    assert_balanced(
        (
            LedgerPosting(
                "ADMIN_ADJUSTMENT_EXPENSE", PostingDirection.DEBIT, RialAmount(10), "ADMIN_CREDIT"
            ),
            LedgerPosting(
                "WALLET:1:ADMIN_GRANT", PostingDirection.CREDIT, RialAmount(10), "ADMIN_CREDIT"
            ),
        )
    )


def test_unbalanced_or_single_posting_rejected() -> None:
    with pytest.raises(ValueError, match="at least two"):
        assert_balanced((LedgerPosting("A", PostingDirection.DEBIT, RialAmount(10), "X"),))
    with pytest.raises(ValueError, match="not balanced"):
        assert_balanced(
            (
                LedgerPosting("A", PostingDirection.DEBIT, RialAmount(10), "X"),
                LedgerPosting("B", PostingDirection.CREDIT, RialAmount(9), "X"),
            )
        )
