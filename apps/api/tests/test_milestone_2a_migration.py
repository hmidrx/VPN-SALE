from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MIGRATION_PATH = Path("apps/api/alembic/versions/0006_milestone_2a_catalog.py")
ENV_PATH = Path("apps/api/alembic/env.py")
REVISION_0002_PATH = Path("apps/api/alembic/versions/0002_milestone_1a_identity.py")


def _migration_module():
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_root_cause_is_documented_live_metadata_create_all() -> None:
    revision_0002 = REVISION_0002_PATH.read_text()
    env_source = ENV_PATH.read_text()
    assert "IdentityBase.metadata.create_all" in revision_0002
    assert "cmd_opts" in env_source
    assert "autogenerate" in env_source
    assert env_source.index("def _target_metadata") < env_source.index(
        "import platform_api.catalog_models"
    )


def test_catalog_table_set_is_explicit_and_complete() -> None:
    migration = _migration_module()
    assert migration.CATALOG_TABLES == frozenset(
        {
            "product_categories",
            "products",
            "product_versions",
            "price_lists",
            "price_list_versions",
            "pricing_rules",
            "pricing_tiers",
            "customer_price_quotes",
            "customer_price_quote_lines",
            "quote_idempotency_records",
        }
    )
    for table in migration.CATALOG_TABLES:
        assert table in migration.EXPECTED_COLUMNS


def test_clean_upgrade_path_creates_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _migration_module()

    def no_existing_tables() -> set[str]:
        return set()

    monkeypatch.setattr(migration, "_existing_catalog_tables", no_existing_tables)
    assert migration._guard_catalog_schema_state() is False


def test_complete_metadata_leak_schema_is_adopted(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _migration_module()
    calls: list[str] = []

    def existing_tables() -> set[str]:
        return set(migration.CATALOG_TABLES)

    monkeypatch.setattr(migration, "_existing_catalog_tables", existing_tables)
    monkeypatch.setattr(
        migration, "_validate_existing_catalog_schema", lambda: calls.append("validated")
    )
    monkeypatch.setattr(migration, "_seed_permissions", lambda: calls.append("seeded"))
    assert migration._guard_catalog_schema_state() is True
    assert calls == ["validated", "seeded"]


def test_partial_catalog_schema_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _migration_module()
    monkeypatch.setattr(migration, "_existing_catalog_tables", lambda: {"product_categories"})
    with pytest.raises(RuntimeError, match="partial Milestone 2-A catalog schema"):
        migration._guard_catalog_schema_state()


def test_required_schema_validation_metadata_names_are_present() -> None:
    migration = _migration_module()
    assert "uq_product_categories_slug" in migration.EXPECTED_UNIQUES["product_categories"]
    assert "ix_product_categories_customer" in migration.EXPECTED_INDEXES["product_categories"]
    assert "ck_customer_price_quotes_final" in migration.EXPECTED_CHECKS["customer_price_quotes"]
    assert "final_amount_minor" in migration.EXPECTED_COLUMNS["customer_price_quotes"]
    assert "lower_inclusive" in migration.EXPECTED_COLUMNS["pricing_tiers"]


def test_no_sample_catalog_data_is_inserted() -> None:
    source = MIGRATION_PATH.read_text().casefold()
    forbidden = ("sample", "demo", "fake product", "pretend", "subscription link")
    assert not any(term in source for term in forbidden)
