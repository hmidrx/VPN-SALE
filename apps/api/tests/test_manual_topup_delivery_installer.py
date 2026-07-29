from pathlib import Path

ROOT = Path(__file__).parents[3]


def test_manual_topup_installer_is_explicit_and_fail_closed() -> None:
    installer = (ROOT / "scripts/install-test-server.sh").read_text()
    verifier = (ROOT / "scripts/verify-test-server.sh").read_text()
    compose = (ROOT / "docker-compose.test-server.yml").read_text()
    assert "--enable-manual-card-topups" in installer
    assert "ENABLE_MANUAL_CARD_TOPUPS=false" in installer
    assert 'VPN_SALE_MANUAL_CARD_TOPUPS_ENABLED "$ENABLE_MANUAL_CARD_TOPUPS"' in installer
    for proof in (
        "manual top-up outbox worker is not running",
        "receipt directory permissions",
        "forbidden destination configuration",
    ):
        assert proof in verifier
    assert "test_server_manual_topup_receipts" in compose
    assert "/var/lib/vpnsale/private/manual-topups" in compose
