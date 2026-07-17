"""Milestone 5-C reseller core."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_milestone_5c_resellers"
down_revision: str = "0012_milestone_5b_customers"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("resellers.read", "Read reseller accounts", UUID("5c000000-0000-4000-8000-000000000001")),
    ("resellers.manage", "Manage reseller accounts", UUID("5c000000-0000-4000-8000-000000000002")),
    (
        "resellers.manage_status",
        "Manage reseller lifecycle",
        UUID("5c000000-0000-4000-8000-000000000003"),
    ),
    (
        "resellers.manage_pricing",
        "Manage reseller pricing",
        UUID("5c000000-0000-4000-8000-000000000004"),
    ),
    (
        "resellers.manage_limits",
        "Manage reseller limits",
        UUID("5c000000-0000-4000-8000-000000000005"),
    ),
    (
        "resellers.manage_customers",
        "Manage reseller customers",
        UUID("5c000000-0000-4000-8000-000000000006"),
    ),
    (
        "resellers.manage_financial",
        "Manage reseller financial accounts",
        UUID("5c000000-0000-4000-8000-000000000007"),
    ),
    (
        "resellers.approve_financial",
        "Approve reseller financial actions",
        UUID("5c000000-0000-4000-8000-000000000008"),
    ),
    (
        "reseller_price_books.read",
        "Read reseller price books",
        UUID("5c000000-0000-4000-8000-000000000009"),
    ),
    (
        "reseller_price_books.manage",
        "Manage reseller price books",
        UUID("5c000000-0000-4000-8000-000000000010"),
    ),
    ("reseller_orders.read", "Read reseller orders", UUID("5c000000-0000-4000-8000-000000000011")),
    (
        "reseller_orders.manage",
        "Manage reseller orders",
        UUID("5c000000-0000-4000-8000-000000000012"),
    ),
)


def _seed_permissions() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    p = sa.table(
        "permissions",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    grant = sa.text(
        "insert into role_permissions (role_id, permission_id) "
        "select roles.id, :permission_id from roles "
        "where machine_name = 'super_admin' on conflict do nothing"
    ).bindparams(sa.bindparam("permission_id", type_=uuid))
    conn = op.get_bind()
    for code, desc, pid in PERMISSIONS:
        conn.execute(
            postgresql.insert(p)
            .values(id=pid, code=code, description=desc)
            .on_conflict_do_update(index_elements=["code"], set_={"description": desc})
        )
        conn.execute(grant, {"permission_id": pid})


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "reseller_tiers",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("limits", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("code", name="uq_reseller_tiers_code"),
    )
    op.create_table(
        "reseller_accounts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column(
            "principal_user_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("business_name", sa.String(180), nullable=False),
        sa.Column("public_brand_label", sa.String(120), nullable=False),
        sa.Column("tier_id", uuid, sa.ForeignKey("reseller_tiers.id", ondelete="RESTRICT")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("settlement_mode", sa.String(32), nullable=False),
        sa.Column("price_book_id", uuid),
        sa.Column("financial_account_id", uuid),
        sa.Column("credit_terms", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("quota_overrides", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("remark_policy", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "parent_reseller_id", uuid, sa.ForeignKey("reseller_accounts.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("suspended_at", sa.DateTime(timezone=True)),
        sa.Column("terminated_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("reference", name="uq_reseller_accounts_reference"),
        sa.UniqueConstraint("principal_user_id", name="uq_reseller_accounts_principal"),
        sa.CheckConstraint(
            (
                "status in ('DRAFT','PENDING_REVIEW','ACTIVE','SUSPENDED','BLOCKED',"
                "'TERMINATED','ARCHIVED')"
            ),
            name="ck_reseller_accounts_status",
        ),
        sa.CheckConstraint(
            "settlement_mode in ('PREPAID','CONTROLLED_CREDIT')",
            name="ck_reseller_accounts_settlement",
        ),
    )
    op.create_index("ix_reseller_accounts_status", "reseller_accounts", ["status", "created_at"])
    op.create_table(
        "reseller_price_books",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("reference", name="uq_reseller_price_books_ref"),
    )
    op.create_table(
        "reseller_pricing_rules",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "price_book_id",
            uuid,
            sa.ForeignKey("reseller_price_books.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope", sa.String(24), nullable=False),
        sa.Column("rule_kind", sa.String(32), nullable=False),
        sa.Column("product_id", uuid, sa.ForeignKey("products.id", ondelete="RESTRICT")),
        sa.Column("category_id", uuid, sa.ForeignKey("product_categories.id", ondelete="RESTRICT")),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("amount_rial", sa.BigInteger()),
        sa.Column("percent_bps", sa.Integer()),
        sa.Column("minimum_price_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("minimum_margin_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "effective_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            (
                "(scope = 'PRODUCT' and product_id is not null and category_id is null) or "
                "(scope = 'CATEGORY' and category_id is not null and product_id is null) or "
                "(scope in ('TIER','DEFAULT') and product_id is null and category_id is null)"
            ),
            name="ck_reseller_pricing_rule_scope_target",
        ),
        sa.CheckConstraint(
            "rule_kind in ('EXACT','PERCENT_DISCOUNT','FIXED_DISCOUNT','TIER_DISCOUNT')",
            name="ck_reseller_pricing_rule_kind",
        ),
        sa.CheckConstraint(
            "scope in ('PRODUCT','CATEGORY','TIER','DEFAULT')",
            name="ck_reseller_pricing_rule_scope",
        ),
        sa.CheckConstraint("priority >= 0", name="ck_reseller_pricing_rule_priority"),
        sa.CheckConstraint(
            "amount_rial is null or amount_rial >= 0",
            name="ck_reseller_pricing_rule_amount",
        ),
        sa.CheckConstraint(
            "percent_bps is null or (percent_bps >= 0 and percent_bps <= 10000)",
            name="ck_reseller_pricing_rule_percent",
        ),
        sa.CheckConstraint(
            "minimum_price_rial >= 0 and minimum_margin_rial >= 0",
            name="ck_reseller_pricing_rule_floors",
        ),
    )
    op.create_index(
        "ix_reseller_pricing_effective",
        "reseller_pricing_rules",
        ["price_book_id", "scope", "effective_at", "expires_at"],
    )
    op.create_index("ix_reseller_pricing_product", "reseller_pricing_rules", ["product_id"])
    op.create_index("ix_reseller_pricing_category", "reseller_pricing_rules", ["category_id"])
    op.create_table(
        "reseller_customer_relationships",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "reseller_id",
            uuid,
            sa.ForeignKey("reseller_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("customer_id", uuid, sa.ForeignKey("identity_users.id", ondelete="RESTRICT")),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("visible_profile", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_reseller_customer_reseller", "reseller_customer_relationships", ["reseller_id", "state"]
    )
    op.create_index(
        "ix_reseller_customer_customer", "reseller_customer_relationships", ["customer_id", "state"]
    )
    op.create_table(
        "reseller_financial_accounts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "reseller_id",
            uuid,
            sa.ForeignKey("reseller_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT")),
        sa.Column("credit_limit_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("utilized_credit_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("credit_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_reference", sa.String(80)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("reseller_id", name="uq_reseller_financial_account"),
        sa.CheckConstraint(
            (
                "credit_limit_rial >= 0 and utilized_credit_rial >= 0 "
                "and utilized_credit_rial <= credit_limit_rial"
            ),
            name="ck_reseller_credit_limit",
        ),
    )
    op.create_table(
        "reseller_order_attributions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "reseller_id",
            uuid,
            sa.ForeignKey("reseller_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("wholesale_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("retail_amount_rial", sa.BigInteger()),
        sa.Column("pricing_snapshot", jsonb, nullable=False),
        sa.Column("remark_snapshot", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("order_id", name="uq_reseller_order_attribution_order"),
    )
    _seed_permissions()


def downgrade() -> None:
    for table in [
        "reseller_order_attributions",
        "reseller_financial_accounts",
        "reseller_customer_relationships",
        "reseller_pricing_rules",
        "reseller_price_books",
        "reseller_accounts",
        "reseller_tiers",
    ]:
        op.drop_table(table)
    conn = op.get_bind()
    codes = [p[0] for p in PERMISSIONS]
    conn.execute(
        sa.text(
            "delete from role_permissions where permission_id in "
            "(select id from permissions where code = any(:codes))"
        ),
        {"codes": codes},
    )
    conn.execute(sa.text("delete from permissions where code = any(:codes)"), {"codes": codes})
