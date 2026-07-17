from __future__ import annotations

import ast
from pathlib import Path

from platform_api.catalog_models import ProductCategoryModel
from platform_api.reseller_models import ResellerPricingRuleModel

MIGRATION = Path("apps/api/alembic/versions/0013_milestone_5c_resellers.py")
CATALOG_MIGRATION = Path("apps/api/alembic/versions/0006_milestone_2a_catalog.py")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_catalog_category_table_is_product_categories() -> None:
    assert ProductCategoryModel.__tablename__ == "product_categories"
    catalog_text = _text(CATALOG_MIGRATION)
    assert 'op.create_table(\n        "product_categories"' in catalog_text
    assert 'sa.ForeignKey("product_categories.id", ondelete="RESTRICT")' in catalog_text


def test_reseller_category_foreign_key_uses_canonical_product_categories() -> None:
    migration_text = _text(MIGRATION)
    model_fk = next(
        fk
        for fk in ResellerPricingRuleModel.__table__.foreign_keys
        if fk.parent.name == "category_id"
    )
    assert model_fk.target_fullname == "product_categories.id"
    assert 'sa.ForeignKey("product_categories.id", ondelete="RESTRICT")' in migration_text
    assert 'ForeignKey("categories.id"' not in migration_text
    assert "REFERENCES categories" not in migration_text


def test_reseller_pricing_rule_scope_target_constraints_match_model_and_migration() -> None:
    migration_text = _text(MIGRATION)
    model_source = Path("apps/api/src/platform_api/reseller_models.py").read_text(encoding="utf-8")
    assert "ck_reseller_pricing_rule_scope_target" in model_source
    assert "ck_reseller_pricing_rule_scope" in model_source
    assert "ck_reseller_pricing_rule_kind" in model_source
    assert "ck_reseller_pricing_rule_scope_target" in migration_text
    assert "scope = 'PRODUCT' and product_id is not null and category_id is null" in migration_text
    assert "scope = 'CATEGORY' and category_id is not null and product_id is null" in migration_text
    assert (
        "scope in ('TIER','DEFAULT') and product_id is null and category_id is null"
        in migration_text
    )


def test_reseller_pricing_rule_indexes_cover_product_and_category_targets() -> None:
    migration_text = _text(MIGRATION)
    assert 'op.create_index("ix_reseller_pricing_product"' in migration_text
    assert 'op.create_index("ix_reseller_pricing_category"' in migration_text
    model_source = Path("apps/api/src/platform_api/reseller_models.py").read_text(encoding="utf-8")
    assert "ix_reseller_pricing_product" in model_source
    assert "ix_reseller_pricing_category" in model_source


def test_milestone_5c_revision_id_stays_within_alembic_limit() -> None:
    tree = ast.parse(_text(MIGRATION), filename=str(MIGRATION))
    revision = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "revision"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )
    assert len(revision) <= 32
