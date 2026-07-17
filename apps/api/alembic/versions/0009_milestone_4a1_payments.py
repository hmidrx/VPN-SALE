"""Milestone 4-A1 provider-neutral payment core."""

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_milestone_4a1_payments"
down_revision: str = "0008_milestone_3b1_orders"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("payment_methods.read", "Read payment methods", UUID("4a100000-0000-4000-8000-000000000001")),
    (
        "payment_methods.manage",
        "Manage payment methods",
        UUID("4a100000-0000-4000-8000-000000000002"),
    ),
    ("payments.read", "Read payments", UUID("4a100000-0000-4000-8000-000000000003")),
    (
        "payments.reconcile",
        "Run payment reconciliation",
        UUID("4a100000-0000-4000-8000-000000000004"),
    ),
    (
        "payment_webhooks.read",
        "Read sanitized payment webhooks",
        UUID("4a100000-0000-4000-8000-000000000005"),
    ),
    (
        "payment_webhooks.retry",
        "Retry payment webhooks",
        UUID("4a100000-0000-4000-8000-000000000006"),
    ),
    ("payment_refunds.read", "Read payment refunds", UUID("4a100000-0000-4000-8000-000000000007")),
    (
        "payment_refunds.manage",
        "Manage payment refunds",
        UUID("4a100000-0000-4000-8000-000000000008"),
    ),
)


def _json_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=False)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "payment_methods",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("adapter_version", sa.String(32), nullable=False),
        sa.Column("method_kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("supported_purposes", jsonb, nullable=False),
        sa.Column("supported_channels", jsonb, nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active_from", sa.DateTime(timezone=True)),
        sa.Column("active_until", sa.DateTime(timezone=True)),
        sa.Column("maintenance_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capability_set", jsonb, nullable=False, server_default=_json_default()),
        sa.Column("secret_reference", sa.String(160)),
        sa.Column("credential_state", sa.String(32), nullable=False, server_default="UNCONFIGURED"),
        sa.Column("credential_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("public_config", jsonb, nullable=False, server_default=_json_default()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("code", name="uq_payment_methods_code"),
        sa.CheckConstraint("currency = 'IRR'", name="ck_payment_methods_currency_irr"),
        sa.CheckConstraint(
            "status in ('DRAFT','ACTIVE','PAUSED','MAINTENANCE','RETIRED','ARCHIVED')",
            name="ck_payment_methods_status",
        ),
    )
    op.create_index("ix_payment_methods_status_priority", "payment_methods", ["status", "priority"])
    op.create_table(
        "payment_method_localizations",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "payment_method_id",
            uuid,
            sa.ForeignKey("payment_methods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("locale", sa.String(8), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.UniqueConstraint(
            "payment_method_id", "locale", name="uq_payment_method_localizations_locale"
        ),
    )
    op.create_table(
        "payment_method_policies",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "payment_method_id",
            uuid,
            sa.ForeignKey("payment_methods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("min_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("max_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.UniqueConstraint(
            "payment_method_id", "purpose", name="uq_payment_method_policies_purpose"
        ),
        sa.CheckConstraint(
            "min_amount_rial > 0 and max_amount_rial >= min_amount_rial",
            name="ck_payment_method_policies_amounts",
        ),
    )
    op.create_table(
        "payment_intents",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(48), nullable=False),
        sa.Column("customer_id", uuid, nullable=False),
        sa.Column(
            "payment_method_id",
            uuid,
            sa.ForeignKey("payment_methods.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("wallet_id", uuid, sa.ForeignKey("wallets.id", ondelete="RESTRICT")),
        sa.Column("order_id", uuid, sa.ForeignKey("orders.id", ondelete="RESTRICT")),
        sa.Column("invoice_id", uuid, sa.ForeignKey("invoices.id", ondelete="RESTRICT")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("reference", name="uq_payment_intents_reference"),
        sa.CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_payment_intents_amount_currency"
        ),
    )
    op.create_index(
        "ix_payment_intents_customer_created", "payment_intents", ["customer_id", "created_at"]
    )
    op.create_index(
        "ix_payment_intents_status_expires", "payment_intents", ["status", "expires_at"]
    )
    op.create_table(
        "payment_attempts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "intent_id",
            uuid,
            sa.ForeignKey("payment_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column("provider_payment_reference", sa.String(160)),
        sa.Column("provider_transaction_reference", sa.String(160)),
        sa.Column("action_url", sa.String(500)),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=_json_default()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("reference", name="uq_payment_attempts_reference"),
        sa.UniqueConstraint(
            "intent_id", "attempt_number", name="uq_payment_attempts_intent_number"
        ),
        sa.UniqueConstraint(
            "provider_transaction_reference", name="uq_payment_attempts_provider_tx"
        ),
        sa.CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_payment_attempts_amount_currency"
        ),
    )
    op.create_index(
        "ix_payment_attempts_intent_status", "payment_attempts", ["intent_id", "status"]
    )
    op.create_table(
        "payment_verifications",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "attempt_id",
            uuid,
            sa.ForeignKey("payment_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_transaction_reference", sa.String(160)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("verified_amount_rial", sa.BigInteger()),
        sa.Column("currency", sa.String(3)),
        sa.Column("failure_category", sa.String(80)),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=_json_default()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_payment_verifications_attempt_created",
        "payment_verifications",
        ["attempt_id", "created_at"],
    )
    op.create_table(
        "payment_settlements",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "intent_id",
            uuid,
            sa.ForeignKey("payment_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            uuid,
            sa.ForeignKey("payment_attempts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_transaction_reference", sa.String(160), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column(
            "journal_entry_id",
            uuid,
            sa.ForeignKey("journal_entries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("refundable_amount_rial", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reference", name="uq_payment_settlements_reference"),
        sa.UniqueConstraint("intent_id", name="uq_payment_settlements_intent"),
        sa.UniqueConstraint(
            "provider_transaction_reference", name="uq_payment_settlements_provider_tx"
        ),
        sa.CheckConstraint(
            "amount_rial > 0 and refundable_amount_rial >= 0 and currency = 'IRR'",
            name="ck_payment_settlements_amount_currency",
        ),
    )
    op.create_table(
        "payment_webhook_inbox",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "payment_method_id", uuid, sa.ForeignKey("payment_methods.id", ondelete="RESTRICT")
        ),
        sa.Column("provider_code", sa.String(48), nullable=False),
        sa.Column("adapter_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("provider_event_reference", sa.String(160)),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("sanitized_headers", jsonb, nullable=False, server_default=_json_default()),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=_json_default()),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correlation_id", sa.String(96), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "provider_code",
            "adapter_version",
            "provider_event_reference",
            name="uq_payment_webhook_provider_event",
        ),
        sa.UniqueConstraint(
            "provider_code",
            "adapter_version",
            "payload_digest",
            name="uq_payment_webhook_payload_digest",
        ),
    )
    op.create_index(
        "ix_payment_webhook_status_received", "payment_webhook_inbox", ["status", "received_at"]
    )
    op.create_table(
        "payment_refunds",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "settlement_id",
            uuid,
            sa.ForeignKey("payment_settlements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="IRR"),
        sa.Column(
            "journal_entry_id", uuid, sa.ForeignKey("journal_entries.id", ondelete="RESTRICT")
        ),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("created_by_admin_id", uuid, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("reference", name="uq_payment_refunds_reference"),
        sa.CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_payment_refunds_amount_currency"
        ),
    )
    op.create_index(
        "ix_payment_refunds_settlement_status", "payment_refunds", ["settlement_id", "status"]
    )
    op.create_table(
        "payment_refund_attempts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "refund_id",
            uuid,
            sa.ForeignKey("payment_refunds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_refund_reference", sa.String(160)),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=_json_default()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "payment_idempotency_records",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("scope_type", sa.String(40), nullable=False),
        sa.Column("scope_id", uuid, nullable=False),
        sa.Column("operation_type", sa.String(80), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_id", uuid),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "operation_type",
            "key_hash",
            name="uq_payment_idempotency_scope",
        ),
    )
    op.create_table(
        "payment_reconciliation_runs",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("mismatch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", jsonb, nullable=False, server_default=_json_default()),
        sa.Column("created_by_admin_id", uuid),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("reference", name="uq_payment_reconciliation_runs_reference"),
    )
    permissions_table = sa.table(
        "permissions",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String(length=120)),
        sa.column("description", sa.String(length=240)),
    )
    for code, desc, ident in PERMISSIONS:
        op.execute(
            postgresql.insert(permissions_table)
            .values(id=ident, code=code, description=desc)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def downgrade() -> None:
    for table in (
        "payment_reconciliation_runs",
        "payment_idempotency_records",
        "payment_refund_attempts",
        "payment_refunds",
        "payment_webhook_inbox",
        "payment_settlements",
        "payment_verifications",
        "payment_attempts",
        "payment_intents",
        "payment_method_policies",
        "payment_method_localizations",
        "payment_methods",
    ):
        op.drop_table(table)
    for code, _, _ in PERMISSIONS:
        op.execute(sa.text("delete from permissions where code = :code").bindparams(code=code))
