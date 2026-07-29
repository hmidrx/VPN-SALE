"""Payment-provider independent rules for reviewed manual wallet top-ups."""

from __future__ import annotations

import re
from enum import StrEnum

MINIMUM_REQUEST_RIAL = 1_000_000
MAX_CUSTOMER_NOTE_LENGTH = 500
MAX_CUSTOMER_MESSAGE_LENGTH = 1_000


class ManualTopupStatus(StrEnum):
    AWAITING_SUPPORT = "AWAITING_SUPPORT"
    AWAITING_RECEIPT = "AWAITING_RECEIPT"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_RESUBMISSION = "NEEDS_RESUBMISSION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


_TRANSITIONS = {
    ManualTopupStatus.AWAITING_SUPPORT: {
        ManualTopupStatus.AWAITING_RECEIPT,
        ManualTopupStatus.CANCELLED,
        ManualTopupStatus.EXPIRED,
    },
    ManualTopupStatus.AWAITING_RECEIPT: {
        ManualTopupStatus.UNDER_REVIEW,
        ManualTopupStatus.CANCELLED,
        ManualTopupStatus.EXPIRED,
    },
    ManualTopupStatus.NEEDS_RESUBMISSION: {
        ManualTopupStatus.UNDER_REVIEW,
        ManualTopupStatus.EXPIRED,
    },
    ManualTopupStatus.UNDER_REVIEW: {
        ManualTopupStatus.NEEDS_RESUBMISSION,
        ManualTopupStatus.APPROVED,
        ManualTopupStatus.REJECTED,
        ManualTopupStatus.EXPIRED,
    },
}


def require_transition(current: ManualTopupStatus, target: ManualTopupStatus) -> None:
    if target not in _TRANSITIONS.get(current, set()):
        raise ValueError(f"manual top-up transition {current} -> {target} is not allowed")


def validate_requested_amount(amount_rial: int, maximum_rial: int) -> int:
    if isinstance(amount_rial, bool) or amount_rial < MINIMUM_REQUEST_RIAL:
        raise ValueError("manual top-up amount is below the minimum")
    if amount_rial > maximum_rial:
        raise ValueError("manual top-up amount exceeds the internal policy")
    return amount_rial


def approval_amounts(verified_rial: int, bonus_rial: int) -> tuple[int, int, int]:
    if isinstance(verified_rial, bool) or verified_rial <= 0:
        raise ValueError("verified transfer must be positive")
    if isinstance(bonus_rial, bool) or bonus_rial < 0:
        raise ValueError("bonus cannot be negative")
    return verified_rial, bonus_rial, verified_rial + bonus_rial


_DIGIT_RUN = re.compile(r"(?<!\d)(?:\d[\s\-]*){16}(?!\d)")


def customer_safe_text(value: str, *, maximum: int = MAX_CUSTOMER_MESSAGE_LENGTH) -> str:
    """Return bounded plain text while preventing this module becoming a destination channel."""
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > maximum or "<" in normalized or ">" in normalized:
        raise ValueError("invalid customer-visible text")
    if _DIGIT_RUN.search(normalized.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))):
        raise ValueError("customer-visible text contains a prohibited digit sequence")
    return normalized
