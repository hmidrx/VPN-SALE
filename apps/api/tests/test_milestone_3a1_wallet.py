from __future__ import annotations

from pathlib import Path

MIGRATION = Path("apps/api/alembic/versions/0007_milestone_3a1_wallet.py")
MODELS = Path("apps/api/src/platform_api/wallet_models.py")
ROUTES = Path("apps/api/src/platform_api/wallet.py")


def test_wallet_schema_uses_integer_rial_and_no_float_columns() -> None:
    source = MODELS.read_text()
    assert "amount_rial" in source
    assert "posted_balance_rial" in source
    assert "reserved_balance_rial" in source
    assert "available_balance_rial" in source
    assert "Float" not in source
    assert "Numeric" not in source


def test_migration_seeds_no_money_or_payments() -> None:
    source = MIGRATION.read_text()
    assert "wallet_policies" in source
    assert "journal_entries" in source
    assert "ledger_postings" in source
    assert 'op.bulk_insert(sa.table("wallets"' not in source
    assert 'op.bulk_insert(sa.table("journal_entries"' not in source
    assert "payment_intent" not in source.lower()
    assert len("0007_milestone_3a1_wallet") <= 32


def test_routes_do_not_expose_direct_balance_setter() -> None:
    source = ROUTES.read_text()
    assert "set balance" not in source.lower()
    assert "posted_balance_rial =" in source
    assert "reconcile" in source
    assert "/adjustments/credit" in source
    assert "/adjustments/debit" in source
