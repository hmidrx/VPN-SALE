"""Milestone 4-A2B2 payment recovery operations."""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_milestone_4a2b2_recovery"
down_revision: str = "0009_milestone_4a1_payments"
branch_labels = None
depends_on = None

PERMISSIONS = (
    ("payment_refunds.read", "Read payment refunds", UUID("4a2b2000-0000-4000-8000-000000000001")),
    (
        "payment_refunds.manage",
        "Request and retry payment refunds",
        UUID("4a2b2000-0000-4000-8000-000000000002"),
    ),
    (
        "payment_refunds.approve",
        "Approve high-risk payment refunds",
        UUID("4a2b2000-0000-4000-8000-000000000003"),
    ),
    (
        "payments.reconcile",
        "Run payment reconciliation",
        UUID("4a2b2000-0000-4000-8000-000000000004"),
    ),
    (
        "payments.repair",
        "Execute approved payment safe repairs",
        UUID("4a2b2000-0000-4000-8000-000000000005"),
    ),
    (
        "payments.late_settlement.manage",
        "Review late payment settlements",
        UUID("4a2b2000-0000-4000-8000-000000000006"),
    ),
    (
        "payments.unapplied.read",
        "Read unapplied payment liabilities",
        UUID("4a2b2000-0000-4000-8000-000000000007"),
    ),
    (
        "payments.unapplied.manage",
        "Resolve unapplied payment liabilities",
        UUID("4a2b2000-0000-4000-8000-000000000008"),
    ),
    (
        "payment_webhooks.recover",
        "Recover reviewed payment webhook dead letters",
        UUID("4a2b2000-0000-4000-8000-000000000009"),
    ),
)


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.add_column("payment_refunds", sa.Column("approved_by_admin_id", uuid, nullable=True))
    op.add_column(
        "payment_refunds", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "payment_refunds",
        sa.Column("approval_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("payment_refunds", sa.Column("rejection_reason", sa.String(500), nullable=True))
    op.add_column(
        "payment_refunds", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_check_constraint(
        "ck_payment_refunds_no_self_approval",
        "payment_refunds",
        "approved_by_admin_id is null or approved_by_admin_id <> created_by_admin_id",
    )
    op.create_table(
        "payment_refund_approvals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "refund_id",
            uuid,
            sa.ForeignKey("payment_refunds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approver_admin_id", uuid, nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "refund_id", "approver_admin_id", "status", name="uq_refund_approval_actor_status"
        ),
        sa.CheckConstraint(
            "status in ('APPROVED','REJECTED','EXPIRED')", name="ck_refund_approvals_status"
        ),
    )
    op.create_table(
        "payment_reconciliation_mismatches",
        sa.Column("id", uuid, primary_key=True),
        sa.Column(
            "run_id",
            uuid,
            sa.ForeignKey("payment_reconciliation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("code", sa.String(96), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column(
            "immutable_evidence", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("stored_state", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("expected_state", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("repair_kind", sa.String(40), nullable=False),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_payment_reconciliation_mismatches_ref"),
    )
    op.create_index(
        "ix_payment_recon_mismatch_scope_status",
        "payment_reconciliation_mismatches",
        ["scope", "status"],
    )
    op.create_table(
        "payment_repair_actions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "mismatch_id",
            uuid,
            sa.ForeignKey("payment_reconciliation_mismatches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        sa.Column("approved_by_admin_id", uuid, nullable=True),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("actions", jsonb, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_payment_repair_actions_ref"),
        sa.UniqueConstraint(
            "mismatch_id", "idempotency_key_hash", name="uq_payment_repair_idempotency"
        ),
    )
    op.create_table(
        "late_settlement_cases",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "intent_id",
            uuid,
            sa.ForeignKey("payment_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_transaction_reference", sa.String(160), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("resolution_reference", sa.String(80), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_late_settlement_cases_ref"),
        sa.UniqueConstraint(
            "provider_transaction_reference", name="uq_late_settlement_provider_tx"
        ),
        sa.CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_late_settlement_amount_currency"
        ),
    )
    op.create_index(
        "ix_late_settlement_status_created", "late_settlement_cases", ["status", "created_at"]
    )
    op.create_table(
        "unapplied_payments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "intent_id",
            uuid,
            sa.ForeignKey("payment_intents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("opaque_provider_reference", sa.String(160), nullable=False),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("customer_id", uuid, nullable=False),
        sa.Column("related_resource_reference", sa.String(80), nullable=True),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("liability_reference", sa.String(80), nullable=True),
        sa.Column("resolution_reference", sa.String(80), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_unapplied_payments_ref"),
        sa.UniqueConstraint("opaque_provider_reference", name="uq_unapplied_provider_ref"),
        sa.CheckConstraint(
            "amount_rial > 0 and currency = 'IRR'", name="ck_unapplied_amount_currency"
        ),
    )
    op.create_index(
        "ix_unapplied_payments_status_created", "unapplied_payments", ["status", "created_at"]
    )
    op.create_table(
        "payment_webhook_recovery_actions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("reference", sa.String(64), nullable=False),
        sa.Column(
            "webhook_id",
            uuid,
            sa.ForeignKey("payment_webhook_inbox.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_by_admin_id", uuid, nullable=False),
        sa.Column("safe_metadata", jsonb, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_webhook_recovery_actions_ref"),
    )
    permissions = sa.table(
        "permissions",
        sa.column("id", uuid),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
    )
    for code, description, permission_id in PERMISSIONS:
        op.execute(
            postgresql.insert(permissions)
            .values(id=permission_id, code=code, description=description)
            .on_conflict_do_nothing(index_elements=["code"])
        )


def downgrade() -> None:
    for code, _, _ in PERMISSIONS:
        op.execute(sa.text("delete from permissions where code = :code").bindparams(code=code))
    op.drop_table("payment_webhook_recovery_actions")
    op.drop_index("ix_unapplied_payments_status_created", table_name="unapplied_payments")
    op.drop_table("unapplied_payments")
    op.drop_index("ix_late_settlement_status_created", table_name="late_settlement_cases")
    op.drop_table("late_settlement_cases")
    op.drop_table("payment_repair_actions")
    op.drop_index(
        "ix_payment_recon_mismatch_scope_status", table_name="payment_reconciliation_mismatches"
    )
    op.drop_table("payment_reconciliation_mismatches")
    op.drop_table("payment_refund_approvals")
    op.drop_constraint("ck_payment_refunds_no_self_approval", "payment_refunds", type_="check")
    op.drop_column("payment_refunds", "version")
    op.drop_column("payment_refunds", "rejection_reason")
    op.drop_column("payment_refunds", "approval_expires_at")
    op.drop_column("payment_refunds", "approved_at")
    op.drop_column("payment_refunds", "approved_by_admin_id")
