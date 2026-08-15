"""Provider-independent rules for starting a paid service entitlement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class ActivationStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVATING = "ACTIVATING"
    RETRY_PENDING = "RETRY_PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class EntitlementClock:
    starts_at: datetime
    activated_at: datetime
    expires_at: datetime


def start_entitlement(activation_instant: datetime, duration_days: int) -> EntitlementClock:
    """Derive all three timestamps from the single verified activation instant."""
    if activation_instant.tzinfo is None or activation_instant.utcoffset() is None:
        raise ValueError("activation instant must be timezone-aware")
    if duration_days <= 0 or duration_days > 3650:
        raise ValueError("duration days out of bounds")
    return EntitlementClock(
        starts_at=activation_instant,
        activated_at=activation_instant,
        expires_at=activation_instant + timedelta(days=duration_days),
    )
