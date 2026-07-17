"""Milestone 3-A1 wallet and double-entry ledger backend."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_milestone_3a1_wallet"
down_revision: str = "0006_milestone_2a_catalog"
branch_labels = None
depends_on = None

PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("wallets.read", "Read wallet records"),
    ("wallets.adjust", "Post manual wallet adjustments"),
    ("wallets.freeze", "Freeze and unfreeze wallets"),
    ("wallets.policy.manage", "Manage wallet policy"),
    ("ledger.read", "Read accounting ledger"),
    ("ledger.reconcile", "Run wallet reconciliation"),
)
SYSTEM_ACCOUNTS: tuple[tuple[str, str], ...] = (
    ("PAYMENT_CLEARING", "PAYMENT_CLEARING"),
    ("ORDER_RESERVATION_CLEARING", "ORDER_RESERVATION_CLEARING"),
    ("ADMIN_ADJUSTMENT_EXPENSE", "ADMIN_ADJUSTMENT_EXPENSE"),
    ("ADMIN_ADJUSTMENT_RECOVERY", "ADMIN_ADJUSTMENT_RECOVERY"),
    ("PROMOTIONAL_EXPENSE", "PROMOTIONAL_EXPENSE"),
    ("REFUND_CLEARING", "REFUND_CLEARING"),
)
TABLES: Sequence[str] = (
    "wallet_reconciliation_runs",
    "wallet_reservations",
    "wallet_credit_lots",
    "ledger_postings",
    "journal_entries",
    "wallet_balance_buckets",
    "wallet_balance_projections",
    "ledger_accounts",
    "wallet_financial_idempotency",
    "wallet_policies",
    "wallets",
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=False)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "wallets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "customer_id",
            uuid,
            sa.ForeignKey("identity_users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("customer_id", "currency", name="uq_wallets_customer_currency"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_wallets_currency_irr"),
        sa.CheckConstraint("status in ('ACTIVE','FROZEN','CLOSED')", name="ck_wallets_status"),
    )
    op.create_index("ix_wallets_customer", "wallets", ["customer_id"])
    op.create_table(
        "wallet_financial_idempotency",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", uuid, nullable=False),
        sa.Column("operation_type", sa.String(64), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_type", sa.String(32)),
        sa.Column("result_id", uuid),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "operation_type",
            "key_hash",
            name="uq_wallet_idempotency_scope_op_key",
        ),
    )
    op.create_table(
        "ledger_accounts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("account_type", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT")),
        sa.Column("system_account", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("code", name="uq_ledger_accounts_code"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_ledger_accounts_currency_irr"),
    )
    op.create_index("ix_ledger_accounts_wallet", "ledger_accounts", ["wallet_id"])
    op.create_table(
        "wallet_policies",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("minimum_topup_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("maximum_topup_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("maximum_wallet_balance_rial", sa.BigInteger(), nullable=False),
        sa.Column("default_reservation_lifetime_seconds", sa.Integer(), nullable=False),
        sa.Column("maximum_reservation_lifetime_seconds", sa.Integer(), nullable=False),
        sa.Column("promotional_credit_expiration_days", sa.Integer(), nullable=False),
        sa.Column("referral_credit_expiration_days", sa.Integer(), nullable=False),
        sa.Column("gift_credit_expiration_days", sa.Integer(), nullable=False),
        sa.Column("spending_bucket_priority", sa.Text(), nullable=False),
        sa.Column(
            "customer_wallet_operations_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "max_transaction_history_page_size", sa.Integer(), nullable=False, server_default="50"
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("currency", name="uq_wallet_policies_currency"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_wallet_policies_currency_irr"),
        sa.CheckConstraint(
            "minimum_topup_amount_rial <= maximum_topup_amount_rial",
            name="ck_wallet_policies_topup_bounds",
        ),
    )
    op.create_table(
        "wallet_balance_projections",
        sa.Column(
            "wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT"), primary_key=True
        ),
        sa.Column("posted_balance_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reserved_balance_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("available_balance_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("promotional_balance_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("expiring_balance_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "posted_balance_rial >= 0 and reserved_balance_rial >= 0 "
            "and available_balance_rial >= 0",
            name="ck_wallet_projection_non_negative",
        ),
    )
    op.create_table(
        "wallet_balance_buckets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("bucket_type", sa.String(32), nullable=False),
        sa.Column("balance_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("wallet_id", "bucket_type", name="uq_wallet_buckets_wallet_type"),
        sa.CheckConstraint("balance_rial >= 0", name="ck_wallet_buckets_balance_non_negative"),
    )
    op.create_table(
        "journal_entries",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("operation_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="POSTED"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT")),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", uuid),
        sa.Column("correlation_id", sa.String(96), nullable=False),
        sa.Column(
            "idempotency_record_id",
            uuid,
            sa.ForeignKey("wallet_financial_idempotency.id", ondelete="SET NULL"),
        ),
        sa.Column("reversal_of_id", uuid, sa.ForeignKey("journal_entries.id", ondelete="RESTRICT")),
        sa.Column("description_code", sa.String(80), nullable=False),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status in ('POSTED','REVERSED')", name="ck_journal_entries_status"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_journal_entries_currency_irr"),
    )
    op.create_index(
        "ix_journal_entries_wallet_posted", "journal_entries", ["wallet_id", "posted_at"]
    )
    op.create_index("ix_journal_entries_correlation", "journal_entries", ["correlation_id"])
    op.create_table(
        "ledger_postings",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "journal_entry_id",
            uuid,
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "ledger_account_id",
            uuid,
            sa.ForeignKey("ledger_accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("direction", sa.String(6), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("posting_order", sa.Integer(), nullable=False),
        sa.Column("purpose_code", sa.String(80), nullable=False),
        sa.UniqueConstraint(
            "journal_entry_id", "posting_order", name="uq_ledger_postings_entry_order"
        ),
        sa.CheckConstraint("direction in ('DEBIT','CREDIT')", name="ck_ledger_postings_direction"),
        sa.CheckConstraint("amount_rial > 0", name="ck_ledger_postings_amount_positive"),
    )
    op.create_index("ix_ledger_postings_account", "ledger_postings", ["ledger_account_id"])
    op.create_table(
        "wallet_credit_lots",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("bucket_type", sa.String(32), nullable=False),
        sa.Column("original_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("remaining_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("source_operation", sa.String(64), nullable=False),
        sa.Column(
            "journal_entry_id",
            uuid,
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.CheckConstraint(
            "original_amount_rial > 0 and remaining_amount_rial >= 0",
            name="ck_wallet_credit_lots_amounts",
        ),
    )
    op.create_index(
        "ix_wallet_credit_lots_expiration", "wallet_credit_lots", ["status", "expires_at"]
    )
    op.create_table(
        "wallet_reservations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("customer_id", uuid, nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("purpose_code", sa.String(80), nullable=False),
        sa.Column("opaque_reference", sa.String(120)),
        sa.Column(
            "idempotency_record_id",
            uuid,
            sa.ForeignKey("wallet_financial_idempotency.id", ondelete="SET NULL"),
        ),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_rial > 0", name="ck_wallet_reservations_amount_positive"),
        sa.CheckConstraint(
            "status in ('ACTIVE','RELEASED','EXPIRED','CAPTURED','CANCELLED')",
            name="ck_wallet_reservations_status",
        ),
    )
    op.create_index(
        "ix_wallet_reservations_wallet_status", "wallet_reservations", ["wallet_id", "status"]
    )
    op.create_index(
        "ix_wallet_reservations_expiration", "wallet_reservations", ["status", "expires_at"]
    )
    op.create_table(
        "wallet_reconciliation_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mismatches", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("repaired", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", uuid),
    )
    op.bulk_insert(
        sa.table(
            "wallet_policies",
            sa.column("id", uuid),
            sa.column("currency", sa.String),
            sa.column("minimum_topup_amount_rial", sa.BigInteger),
            sa.column("maximum_topup_amount_rial", sa.BigInteger),
            sa.column("maximum_wallet_balance_rial", sa.BigInteger),
            sa.column("default_reservation_lifetime_seconds", sa.Integer),
            sa.column("maximum_reservation_lifetime_seconds", sa.Integer),
            sa.column("promotional_credit_expiration_days", sa.Integer),
            sa.column("referral_credit_expiration_days", sa.Integer),
            sa.column("gift_credit_expiration_days", sa.Integer),
            sa.column("spending_bucket_priority", sa.Text),
            sa.column("customer_wallet_operations_enabled", sa.Boolean),
            sa.column("max_transaction_history_page_size", sa.Integer),
            sa.column("version", sa.Integer),
        ),
        [
            {
                "id": "d277450e-af5f-44fa-b5ae-d5556b390301",
                "currency": "IRR",
                "minimum_topup_amount_rial": 100000,
                "maximum_topup_amount_rial": 500000000,
                "maximum_wallet_balance_rial": 2000000000,
                "default_reservation_lifetime_seconds": 900,
                "maximum_reservation_lifetime_seconds": 3600,
                "promotional_credit_expiration_days": 30,
                "referral_credit_expiration_days": 90,
                "gift_credit_expiration_days": 180,
                "spending_bucket_priority": "CASH,REFUND,ADMIN_GRANT,GIFT,REFERRAL,PROMOTIONAL",
                "customer_wallet_operations_enabled": True,
                "max_transaction_history_page_size": 50,
                "version": 1,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "ledger_accounts",
            sa.column("id", uuid),
            sa.column("code", sa.String),
            sa.column("account_type", sa.String),
            sa.column("currency", sa.String),
            sa.column("system_account", sa.Boolean),
        ),
        [
            {
                "id": f"d277450e-af5f-44fa-b5ae-d5556b39{i:04d}",
                "code": c,
                "account_type": t,
                "currency": "IRR",
                "system_account": True,
            }
            for i, (c, t) in enumerate(SYSTEM_ACCOUNTS, 10)
        ],
    )
    op.bulk_insert(
        sa.table(
            "permissions",
            sa.column("id", uuid),
            sa.column("code", sa.String),
            sa.column("description", sa.String),
        ),
        [
            {"id": f"d277450e-af5f-44fa-b5ae-d5556b38{i:04d}", "code": c, "description": d}
            for i, (c, d) in enumerate(PERMISSIONS, 10)
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("delete from permissions where code in :codes")
        .bindparams(sa.bindparam("codes", expanding=True))
        .params(codes=[p[0] for p in PERMISSIONS])
    )
    for table in TABLES:
        op.drop_table(table)
