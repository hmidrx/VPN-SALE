from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAYMENTS = (ROOT / "apps/api/src/platform_api/payments.py").read_text()
MIGRATION = (ROOT / "apps/api/alembic/versions/0010_milestone_4a2b2_recovery.py").read_text()


def test_refund_approval_and_invalid_webhook_recovery_guards_exist() -> None:
    assert "REFUND_SELF_APPROVAL_DENIED" in PAYMENTS
    assert "INVALID_SIGNATURE_WEBHOOK_UNTRUSTED" in PAYMENTS
    assert '"/refunds/{refund_reference}/approve"' in PAYMENTS
    assert '"/webhooks/{webhook_reference}/recover"' in PAYMENTS


def test_reconciliation_safe_repair_and_late_unapplied_routes_exist() -> None:
    for needle in [
        '"/reconciliation/dry-run"',
        '"/reconciliation/repair-plan"',
        '"/late-settlements"',
        '"/unapplied-payments"',
        "CRITICAL_MISMATCH_NOT_REPAIRABLE",
    ]:
        assert needle in PAYMENTS


def test_migration_seeds_recovery_permissions_and_constraints() -> None:
    for permission in [
        "payment_refunds.read",
        "payment_refunds.manage",
        "payment_refunds.approve",
        "payments.reconcile",
        "payments.repair",
        "payments.late_settlement.manage",
        "payments.unapplied.read",
        "payments.unapplied.manage",
        "payment_webhooks.recover",
    ]:
        assert permission in MIGRATION
    assert "ck_payment_refunds_no_self_approval" in MIGRATION
    assert "uq_payment_repair_idempotency" in MIGRATION
    assert "uq_unapplied_provider_ref" in MIGRATION
