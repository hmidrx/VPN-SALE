from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

MAX_RIAL_AMOUNT = 9_999_999_999_999
IRR = "IRR"


class WalletStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class LedgerAccountType(StrEnum):
    CUSTOMER_WALLET_LIABILITY = "CUSTOMER_WALLET_LIABILITY"
    CUSTOMER_PROMOTIONAL_LIABILITY = "CUSTOMER_PROMOTIONAL_LIABILITY"
    CUSTOMER_REFUND_LIABILITY = "CUSTOMER_REFUND_LIABILITY"
    CUSTOMER_REFERRAL_LIABILITY = "CUSTOMER_REFERRAL_LIABILITY"
    PAYMENT_CLEARING = "PAYMENT_CLEARING"
    ORDER_RESERVATION_CLEARING = "ORDER_RESERVATION_CLEARING"
    ADMIN_ADJUSTMENT_EXPENSE = "ADMIN_ADJUSTMENT_EXPENSE"
    ADMIN_ADJUSTMENT_RECOVERY = "ADMIN_ADJUSTMENT_RECOVERY"
    PROMOTIONAL_EXPENSE = "PROMOTIONAL_EXPENSE"
    REFUND_CLEARING = "REFUND_CLEARING"


class JournalEntryStatus(StrEnum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PostingDirection(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class WalletBalanceBucket(StrEnum):
    CASH = "CASH"
    REFUND = "REFUND"
    PROMOTIONAL = "PROMOTIONAL"
    REFERRAL = "REFERRAL"
    GIFT = "GIFT"
    ADMIN_GRANT = "ADMIN_GRANT"


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    CAPTURED = "CAPTURED"
    CANCELLED = "CANCELLED"


class FinancialOperationType(StrEnum):
    ADMIN_CREDIT = "ADMIN_CREDIT"
    ADMIN_DEBIT = "ADMIN_DEBIT"
    REVERSAL = "REVERSAL"
    CREDIT_EXPIRATION = "CREDIT_EXPIRATION"
    RESERVATION_CREATED = "RESERVATION_CREATED"
    RESERVATION_RELEASED = "RESERVATION_RELEASED"
    RESERVATION_EXPIRED = "RESERVATION_EXPIRED"
    RESERVATION_CAPTURED = "RESERVATION_CAPTURED"


@dataclass(frozen=True)
class RialAmount:
    value: int

    def __post_init__(self) -> None:
        if type(self.value) is not int:
            raise TypeError("amount_rial must be an integer rial value")
        if self.value <= 0:
            raise ValueError("amount_rial must be positive")
        if self.value > MAX_RIAL_AMOUNT:
            raise OverflowError("amount_rial exceeds maximum")


@dataclass(frozen=True)
class LedgerPosting:
    account_code: str
    direction: PostingDirection
    amount_rial: RialAmount
    purpose_code: str


def assert_balanced(postings: tuple[LedgerPosting, ...]) -> None:
    if len(postings) < 2:
        raise ValueError("journal entries require at least two postings")
    debits = sum(p.amount_rial.value for p in postings if p.direction == PostingDirection.DEBIT)
    credits = sum(p.amount_rial.value for p in postings if p.direction == PostingDirection.CREDIT)
    if debits != credits:
        raise ValueError("journal entry is not balanced")


def utc_now() -> datetime:
    return datetime.now(UTC)
