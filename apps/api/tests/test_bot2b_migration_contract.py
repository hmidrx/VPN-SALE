from __future__ import annotations

from pathlib import Path


def test_bot2b_activation_migration_preserves_deferred_clock_and_encrypted_delivery() -> None:
    source = Path("apps/api/alembic/versions/0038_service_activation_delivery.py").read_text()
    assert 'revision: str = "0038_service_activation_delivery"' in source
    assert 'down_revision: str = "0037_real_fulfillment"' in source
    assert '"service_activation_requests"' in source
    assert '"activation_instant"' in source
    assert '"encrypted_payload"' in source
    assert '"encryption_key_version"' in source
    assert '"payload_sha256"' in source
    assert "PENDING_ACTIVATION" in source
