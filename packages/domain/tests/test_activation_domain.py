from datetime import UTC, datetime, timedelta

import pytest
from vpnsale_domain.activation import start_entitlement


def test_entitlement_clock_starts_only_at_activation() -> None:
    activated = datetime(2026, 8, 15, 12, tzinfo=UTC)
    clock = start_entitlement(activated, 30)
    assert clock.starts_at == clock.activated_at == activated
    assert clock.expires_at == activated + timedelta(days=30)


def test_entitlement_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        start_entitlement(datetime(2026, 8, 15), 30)
