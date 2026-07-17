from pathlib import Path


def test_milestone_5c_migration_has_permissions_and_tables() -> None:
    migration = Path("apps/api/alembic/versions/0013_milestone_5c_resellers.py").read_text()
    for name in [
        "reseller_accounts",
        "reseller_price_books",
        "reseller_customer_relationships",
        "reseller_financial_accounts",
        "reseller_order_attributions",
    ]:
        assert name in migration
    for perm in [
        "resellers.read",
        "resellers.manage_financial",
        "resellers.approve_financial",
        "reseller_orders.manage",
    ]:
        assert perm in migration


def test_admin_web_reseller_routes_exist() -> None:
    for path in [
        "apps/admin-web/app/management/resellers/page.tsx",
        "apps/admin-web/app/management/reseller-price-books/page.tsx",
        "apps/admin-web/app/management/reseller-tiers/page.tsx",
    ]:
        text = Path(path).read_text()
        assert 'dir="rtl"' in text
        assert "VPN" not in text or "جعلی" in text
