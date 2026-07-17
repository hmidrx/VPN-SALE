"""Milestone 2-A catalog and pricing backend."""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_milestone_2a_catalog"
down_revision: str = "0005_milestone_1d_a"
branch_labels = None
depends_on = None

CATALOG_TABLES: frozenset[str] = frozenset(
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

EXPECTED_COLUMNS: dict[str, frozenset[str]] = {
    "product_categories": frozenset(
        {
            "id",
            "slug",
            "status",
            "display_order",
            "customer_visible",
            "localizations",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "products": frozenset(
        {
            "id",
            "category_id",
            "machine_code",
            "status",
            "customer_visible",
            "display_order",
            "current_version_id",
            "localizations",
            "availability",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "product_versions": frozenset(
        {
            "id",
            "product_id",
            "version_number",
            "status",
            "product_type",
            "definition_snapshot",
            "options_snapshot",
            "constraints_snapshot",
            "fulfillment_requirements_snapshot",
            "created_at",
        }
    ),
    "price_lists": frozenset({"id", "key", "scope", "active", "created_at"}),
    "price_list_versions": frozenset(
        {"id", "price_list_id", "version_number", "currency", "priority", "active", "active_from"}
    ),
    "pricing_rules": frozenset(
        {
            "id",
            "price_list_version_id",
            "code",
            "rule_type",
            "amount_minor",
            "unit_size",
            "priority",
        }
    ),
    "pricing_tiers": frozenset(
        {"id", "pricing_rule_id", "lower_inclusive", "unit_amount_minor", "priority"}
    ),
    "customer_price_quotes": frozenset(
        {
            "id",
            "reference",
            "product_id",
            "product_version_id",
            "customer_id",
            "operation",
            "selected_options",
            "price_list_version_id",
            "currency",
            "subtotal_minor",
            "final_amount_minor",
            "pricing_engine_version",
            "status",
            "issued_at",
            "expires_at",
        }
    ),
    "customer_price_quote_lines": frozenset(
        {"id", "quote_id", "component_code", "label", "amount_minor", "display_order"}
    ),
    "quote_idempotency_records": frozenset(
        {"id", "customer_id", "key_hash", "request_fingerprint", "expires_at"}
    ),
}

EXPECTED_INDEXES: dict[str, frozenset[str]] = {
    "product_categories": frozenset({"ix_product_categories_customer"}),
    "products": frozenset({"ix_products_customer", "ix_products_category"}),
    "product_versions": frozenset({"ix_product_versions_product_status"}),
    "price_list_versions": frozenset({"ix_price_list_versions_resolution"}),
    "pricing_rules": frozenset({"ix_pricing_rules_price_list_version"}),
    "customer_price_quotes": frozenset(
        {"ix_customer_price_quotes_customer", "ix_customer_price_quotes_reference"}
    ),
    "customer_price_quote_lines": frozenset({"ix_customer_price_quote_lines_quote"}),
    "quote_idempotency_records": frozenset({"ix_quote_idempotency_expires"}),
}

EXPECTED_UNIQUES: dict[str, frozenset[str]] = {
    "product_categories": frozenset({"uq_product_categories_slug"}),
    "products": frozenset({"uq_products_machine_code"}),
    "product_versions": frozenset({"uq_product_versions_product_number"}),
    "price_lists": frozenset({"uq_price_lists_key"}),
    "price_list_versions": frozenset({"uq_price_list_versions_number"}),
    "pricing_rules": frozenset(
        {"uq_pricing_rules_version_code", "uq_pricing_rules_version_priority"}
    ),
    "pricing_tiers": frozenset({"uq_pricing_tiers_rule_priority"}),
    "customer_price_quotes": frozenset({"uq_customer_price_quotes_reference"}),
    "quote_idempotency_records": frozenset({"uq_quote_idempotency_customer_key"}),
}

EXPECTED_CHECKS: dict[str, frozenset[str]] = {
    "product_categories": frozenset(
        {"ck_product_categories_status", "ck_product_categories_display_order"}
    ),
    "products": frozenset({"ck_products_status"}),
    "product_versions": frozenset(
        {"ck_product_versions_number", "ck_product_versions_status", "ck_product_versions_type"}
    ),
    "price_list_versions": frozenset(
        {"ck_price_list_versions_number", "ck_price_list_versions_priority"}
    ),
    "pricing_rules": frozenset(
        {"ck_pricing_rules_amount_non_negative", "ck_pricing_rules_unit_size"}
    ),
    "pricing_tiers": frozenset(
        {"ck_pricing_tiers_lower", "ck_pricing_tiers_bounds", "ck_pricing_tiers_amount"}
    ),
    "customer_price_quotes": frozenset(
        {"ck_customer_price_quotes_subtotal", "ck_customer_price_quotes_final"}
    ),
}


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _existing_catalog_tables() -> set[str]:
    inspector = _inspector()
    names = set(inspector.get_table_names())
    return CATALOG_TABLES.intersection(names)


def _named(items: list[dict[str, object]], key: str = "name") -> set[str]:
    return {str(item[key]) for item in items if item.get(key)}


def _validate_existing_catalog_schema() -> None:
    inspector = _inspector()
    for table in sorted(CATALOG_TABLES):
        columns = {str(column["name"]): column for column in inspector.get_columns(table)}
        missing_columns = EXPECTED_COLUMNS[table] - set(columns)
        if missing_columns:
            raise RuntimeError(
                f"existing catalog table {table} is missing columns: {sorted(missing_columns)}"
            )
        pk = inspector.get_pk_constraint(table)
        if "id" not in set(pk.get("constrained_columns") or []):
            raise RuntimeError(f"existing catalog table {table} does not have id primary key")
        for column_name in ("id",):
            if "UUID" not in str(columns[column_name]["type"]).upper():
                raise RuntimeError(
                    f"existing catalog table {table}.{column_name} is not PostgreSQL UUID"
                )
        indexes = _named(inspector.get_indexes(table))
        missing_indexes = EXPECTED_INDEXES.get(table, frozenset()) - indexes
        for index_name in sorted(missing_indexes):
            # These indexes are deterministic and safe to add to an already-empty
            # or populated metadata-leak table because they do not alter data.
            if index_name == "ix_product_categories_customer":
                op.create_index(index_name, table, ["status", "customer_visible", "display_order"])
            elif index_name == "ix_products_customer":
                op.create_index(index_name, table, ["status", "customer_visible", "display_order"])
            elif index_name == "ix_products_category":
                op.create_index(index_name, table, ["category_id"])
            elif index_name == "ix_product_versions_product_status":
                op.create_index(index_name, table, ["product_id", "status"])
            elif index_name == "ix_price_list_versions_resolution":
                op.create_index(
                    index_name, table, ["active", "segment_key", "priority", "active_from"]
                )
            elif index_name == "ix_pricing_rules_price_list_version":
                op.create_index(index_name, table, ["price_list_version_id"])
            elif index_name == "ix_customer_price_quotes_customer":
                op.create_index(index_name, table, ["customer_id", "issued_at"])
            elif index_name == "ix_customer_price_quotes_reference":
                op.create_index(index_name, table, ["reference"])
            elif index_name == "ix_customer_price_quote_lines_quote":
                op.create_index(index_name, table, ["quote_id", "display_order"])
            elif index_name == "ix_quote_idempotency_expires":
                op.create_index(index_name, table, ["expires_at"])
        uniques = _named(inspector.get_unique_constraints(table))
        missing_uniques = EXPECTED_UNIQUES.get(table, frozenset()) - uniques
        if missing_uniques:
            raise RuntimeError(
                "existing catalog table "
                f"{table} is missing unique constraints: {sorted(missing_uniques)}"
            )
        checks = _named(inspector.get_check_constraints(table))
        missing_checks = EXPECTED_CHECKS.get(table, frozenset()) - checks
        if missing_checks:
            raise RuntimeError(
                "existing catalog table "
                f"{table} is missing check constraints: {sorted(missing_checks)}"
            )
        required_not_null = EXPECTED_COLUMNS[table] - {
            "icon_reference",
            "admin_notes",
            "current_version_id",
            "published_at",
            "retired_at",
            "segment_key",
            "active_until",
            "operation",
            "selector_code",
            "upper_exclusive",
            "quote_id",
        }
        nullable = {name for name, column in columns.items() if bool(column.get("nullable"))}
        nullable_required = required_not_null.intersection(nullable)
        if nullable_required:
            raise RuntimeError(
                "existing catalog table "
                f"{table} has nullable required columns: {sorted(nullable_required)}"
            )
        fks = inspector.get_foreign_keys(table)
        if table not in {"product_categories", "price_lists"} and not fks:
            raise RuntimeError(f"existing catalog table {table} is missing foreign keys")
        for column_name in (
            "amount_minor",
            "subtotal_minor",
            "final_amount_minor",
            "lower_inclusive",
            "unit_amount_minor",
        ):
            if column_name in columns and "BIGINT" not in str(columns[column_name]["type"]).upper():
                raise RuntimeError(
                    f"existing catalog table {table}.{column_name} is not BigInteger"
                )


def _seed_permissions() -> None:
    permissions: Sequence[tuple[str, str, UUID]] = (
        (
            "catalog.read",
            "Read catalog administration data",
            UUID("94b85bba-c279-488d-a12e-b6554ec4b897"),
        ),
        (
            "catalog.create",
            "Create catalog administration data",
            UUID("07ad0f03-71e1-4b0e-a735-58a270d15085"),
        ),
        (
            "catalog.update",
            "Update catalog administration data",
            UUID("7990f5cc-6d96-44aa-b984-13639ea8d665"),
        ),
        (
            "catalog.publish",
            "Publish catalog product versions",
            UUID("cc02701a-cb6a-438c-a17a-762aee762c72"),
        ),
        (
            "pricing.read",
            "Read pricing previews and rules",
            UUID("69c8ff9a-8687-43c6-b432-1e66524747f7"),
        ),
        (
            "pricing.manage",
            "Manage price lists and pricing rules",
            UUID("5f61d8e5-fb95-4995-8b45-afae2f1e83e2"),
        ),
        (
            "quotes.read",
            "Read customer quote records",
            UUID("d6ab90d6-bba6-4db4-8642-68a298f8a609"),
        ),
    )
    permissions_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String(length=120)),
        sa.column("description", sa.String(length=240)),
    )
    for code, desc, ident in permissions:
        op.execute(
            postgresql.insert(permissions_table)
            .values(id=ident, code=code, description=desc)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def _guard_catalog_schema_state() -> bool:
    existing = _existing_catalog_tables()
    if not existing:
        return False
    if existing == set(CATALOG_TABLES):
        _validate_existing_catalog_schema()
        _seed_permissions()
        return True
    missing = sorted(CATALOG_TABLES - existing)
    present = sorted(existing)
    raise RuntimeError(
        "partial Milestone 2-A catalog schema exists before revision 0006; "
        f"present={present}, missing={missing}"
    )


def upgrade() -> None:
    if _guard_catalog_schema_state():
        return
    json_type = postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")
    op.create_table(
        "product_categories",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("customer_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("icon_reference", sa.String(160)),
        sa.Column("admin_notes", sa.Text()),
        sa.Column(
            "localizations", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "status in ('DRAFT','ACTIVE','ARCHIVED')", name="ck_product_categories_status"
        ),
        sa.CheckConstraint("display_order >= 0", name="ck_product_categories_display_order"),
        sa.UniqueConstraint("slug", name="uq_product_categories_slug"),
    )
    op.create_index(
        "ix_product_categories_customer",
        "product_categories",
        ["status", "customer_visible", "display_order"],
    )
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "category_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("product_categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("machine_code", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("customer_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("admin_notes", sa.Text()),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=False)),
        sa.Column(
            "localizations", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("availability", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "status in ('DRAFT','ACTIVE','PAUSED','RETIRED','ARCHIVED')", name="ck_products_status"
        ),
        sa.UniqueConstraint("machine_code", name="uq_products_machine_code"),
    )
    op.create_index(
        "ix_products_customer", "products", ["status", "customer_visible", "display_order"]
    )
    op.create_index("ix_products_category", "products", ["category_id"])
    op.create_table(
        "product_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="DRAFT"),
        sa.Column("product_type", sa.String(24), nullable=False),
        sa.Column("definition_snapshot", json_type, nullable=False),
        sa.Column("options_snapshot", json_type, nullable=False),
        sa.Column(
            "constraints_snapshot", json_type, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "fulfillment_requirements_snapshot",
            json_type,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("version_number > 0", name="ck_product_versions_number"),
        sa.CheckConstraint(
            "status in ('DRAFT','PUBLISHED','SUPERSEDED','RETIRED')",
            name="ck_product_versions_status",
        ),
        sa.CheckConstraint(
            "product_type in ('FIXED_PLAN','CUSTOM_PLAN')", name="ck_product_versions_type"
        ),
        sa.UniqueConstraint(
            "product_id", "version_number", name="uq_product_versions_product_number"
        ),
    )
    op.create_foreign_key(
        "fk_products_current_version",
        "products",
        "product_versions",
        ["current_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_product_versions_product_status", "product_versions", ["product_id", "status"]
    )
    op.create_table(
        "price_lists",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False, server_default="DEFAULT_RETAIL"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("key", name="uq_price_lists_key"),
    )
    op.create_table(
        "price_list_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "price_list_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("price_lists.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("segment_key", sa.String(80)),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_until", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("version_number > 0", name="ck_price_list_versions_number"),
        sa.CheckConstraint("priority >= 0", name="ck_price_list_versions_priority"),
        sa.UniqueConstraint(
            "price_list_id", "version_number", name="uq_price_list_versions_number"
        ),
    )
    op.create_index(
        "ix_price_list_versions_resolution",
        "price_list_versions",
        ["active", "segment_key", "priority", "active_from"],
    )
    op.create_table(
        "pricing_rules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "price_list_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("price_list_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("rule_type", sa.String(40), nullable=False),
        sa.Column("operation", sa.String(32)),
        sa.Column("selector_code", sa.String(80)),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("unit_size", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("percentage_basis_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column(
            "customer_label", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.CheckConstraint("amount_minor >= 0", name="ck_pricing_rules_amount_non_negative"),
        sa.CheckConstraint("unit_size > 0", name="ck_pricing_rules_unit_size"),
        sa.UniqueConstraint("price_list_version_id", "code", name="uq_pricing_rules_version_code"),
        sa.UniqueConstraint(
            "price_list_version_id", "priority", name="uq_pricing_rules_version_priority"
        ),
    )
    op.create_index(
        "ix_pricing_rules_price_list_version", "pricing_rules", ["price_list_version_id"]
    )
    op.create_table(
        "pricing_tiers",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "pricing_rule_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("pricing_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("lower_inclusive", sa.BigInteger(), nullable=False),
        sa.Column("upper_exclusive", sa.BigInteger()),
        sa.Column("unit_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.CheckConstraint("lower_inclusive >= 0", name="ck_pricing_tiers_lower"),
        sa.CheckConstraint(
            "upper_exclusive is null or upper_exclusive > lower_inclusive",
            name="ck_pricing_tiers_bounds",
        ),
        sa.CheckConstraint("unit_amount_minor >= 0", name="ck_pricing_tiers_amount"),
        sa.UniqueConstraint("pricing_rule_id", "priority", name="uq_pricing_tiers_rule_priority"),
    )
    op.create_table(
        "customer_price_quotes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "product_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("product_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("selected_options", json_type, nullable=False),
        sa.Column(
            "price_list_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("price_list_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("subtotal_minor", sa.BigInteger(), nullable=False),
        sa.Column("final_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("pricing_engine_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="ACTIVE"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "validation_summary", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.CheckConstraint("subtotal_minor >= 0", name="ck_customer_price_quotes_subtotal"),
        sa.CheckConstraint("final_amount_minor > 0", name="ck_customer_price_quotes_final"),
        sa.UniqueConstraint("reference", name="uq_customer_price_quotes_reference"),
    )
    op.create_index(
        "ix_customer_price_quotes_customer", "customer_price_quotes", ["customer_id", "issued_at"]
    )
    op.create_index("ix_customer_price_quotes_reference", "customer_price_quotes", ["reference"])
    op.create_table(
        "customer_price_quote_lines",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("customer_price_quotes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("component_code", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_customer_price_quote_lines_quote",
        "customer_price_quote_lines",
        ["quote_id", "display_order"],
    )
    op.create_table(
        "quote_idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "customer_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.String(96), nullable=False),
        sa.Column("request_fingerprint", sa.String(96), nullable=False),
        sa.Column(
            "quote_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("customer_price_quotes.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("customer_id", "key_hash", name="uq_quote_idempotency_customer_key"),
    )
    op.create_index("ix_quote_idempotency_expires", "quote_idempotency_records", ["expires_at"])
    _seed_permissions()


def downgrade() -> None:
    for code in (
        "catalog.read",
        "catalog.create",
        "catalog.update",
        "catalog.publish",
        "pricing.read",
        "pricing.manage",
        "quotes.read",
    ):
        op.execute(sa.text("delete from permissions where code = :code").bindparams(code=code))
    for table in (
        "quote_idempotency_records",
        "customer_price_quote_lines",
        "customer_price_quotes",
        "pricing_tiers",
        "pricing_rules",
        "price_list_versions",
        "price_lists",
    ):
        op.drop_table(table)
    op.drop_constraint("fk_products_current_version", "products", type_="foreignkey")
    op.drop_table("product_versions")
    op.drop_table("products")
    op.drop_table("product_categories")
