"""Add private, reviewed manual wallet top-up persistence.

Revision ID: 0032_manual_card_topups
Revises: 0031_wallet_topup_minimum
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032_manual_card_topups"
down_revision: str = "0031_wallet_topup_minimum"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=False)


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def upgrade() -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        "manual_topup_requests",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("reference", sa.String(48), nullable=False),
        sa.Column("customer_id", _UUID, nullable=False),
        sa.Column("wallet_id", _UUID, nullable=False),
        sa.Column("requested_amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("source_channel", sa.String(24), nullable=False),
        sa.Column("current_receipt_id", _UUID, nullable=True),
        sa.Column("customer_note", sa.String(500), nullable=True),
        sa.Column("admin_visible_state", sa.String(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_admin_id", _UUID, nullable=True),
        sa.Column("rejected_by_admin_id", _UUID, nullable=True),
        sa.Column("verified_transfer_amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("bonus_amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("total_credited_amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("cash_journal_entry_id", _UUID, nullable=True),
        sa.Column("bonus_journal_entry_id", _UUID, nullable=True),
        sa.Column("customer_message", sa.String(1000), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        created_at,
        updated_at,
        sa.CheckConstraint("currency = 'IRR'", name="ck_manual_topup_request_currency"),
        sa.CheckConstraint(
            "requested_amount_rial >= 1000000", name="ck_manual_topup_request_minimum"
        ),
        sa.CheckConstraint("version > 0", name="ck_manual_topup_request_version"),
        sa.CheckConstraint(
            "status in ('AWAITING_SUPPORT','AWAITING_RECEIPT','UNDER_REVIEW',"
            "'NEEDS_RESUBMISSION','APPROVED','REJECTED','CANCELLED','EXPIRED')",
            name="ck_manual_topup_request_status",
        ),
        sa.CheckConstraint(
            "(status <> 'APPROVED') OR (verified_transfer_amount_rial > 0 AND "
            "bonus_amount_rial >= 0 AND total_credited_amount_rial = "
            "verified_transfer_amount_rial + bonus_amount_rial AND "
            "cash_journal_entry_id IS NOT NULL)",
            name="ck_manual_topup_request_approved_amounts",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by_admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["cash_journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["bonus_journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
        sa.UniqueConstraint("cash_journal_entry_id"),
        sa.UniqueConstraint("bonus_journal_entry_id"),
    )
    op.create_index(
        "ix_manual_topup_customer_status_created",
        "manual_topup_requests",
        ["customer_id", "status", "created_at"],
    )
    op.create_index(
        "ix_manual_topup_review_queue",
        "manual_topup_requests",
        ["status", "submitted_at", "created_at"],
    )

    op.create_table(
        "manual_topup_receipts",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("reference", sa.String(48), nullable=False),
        sa.Column("request_id", _UUID, nullable=False),
        sa.Column("receipt_version", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(160), nullable=False),
        sa.Column("sanitized_sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source_channel", sa.String(24), nullable=False),
        sa.Column("telegram_file_unique_id_hash", sa.String(64), nullable=True),
        sa.Column("security_state", sa.String(24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "receipt_version > 0 AND byte_size > 0", name="ck_manual_topup_receipt_values"
        ),
        sa.ForeignKeyConstraint(["request_id"], ["manual_topup_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
        sa.UniqueConstraint("storage_key"),
        sa.UniqueConstraint(
            "request_id", "receipt_version", name="uq_manual_topup_receipt_version"
        ),
    )
    op.create_index("ix_manual_topup_receipt_hash", "manual_topup_receipts", ["sanitized_sha256"])

    op.create_table(
        "manual_topup_decisions",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("request_id", _UUID, nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("admin_id", _UUID, nullable=False),
        sa.Column("expected_request_version", sa.Integer(), nullable=False),
        sa.Column("verified_transfer_amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("bonus_amount_rial", sa.BigInteger(), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("internal_note", sa.String(1000), nullable=True),
        sa.Column("customer_message", sa.String(1000), nullable=True),
        sa.Column("cash_journal_entry_id", _UUID, nullable=True),
        sa.Column("bonus_journal_entry_id", _UUID, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["request_id"], ["manual_topup_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["admin_id"], ["admins.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["cash_journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["bonus_journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id", "decision", name="uq_manual_topup_decision_request_kind"),
        sa.UniqueConstraint("cash_journal_entry_id"),
        sa.UniqueConstraint("bonus_journal_entry_id"),
    )
    op.create_table(
        "manual_topup_idempotency",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_reference", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope", "scope_id", "operation", "key_hash", name="uq_manual_topup_idempotency"
        ),
    )
    op.create_table(
        "manual_topup_messages",
        sa.Column("reference", sa.String(48), nullable=False),
        sa.Column("request_id", _UUID, nullable=False),
        sa.Column("sender_type", sa.String(16), nullable=False),
        sa.Column("sender_reference", sa.String(64), nullable=False),
        sa.Column("visibility", sa.String(16), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["request_id"], ["manual_topup_requests.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("reference"),
    )
    op.create_table(
        "manual_topup_notification_outbox",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("event_reference", sa.String(64), nullable=False),
        sa.Column("deduplication_key", sa.String(96), nullable=False),
        sa.Column("request_id", _UUID, nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("customer_id", _UUID, nullable=False),
        sa.Column("delivery_channel", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status in ('PENDING','PROCESSING','SENT','FAILED')",
            name="ck_manual_topup_outbox_status",
        ),
        sa.ForeignKeyConstraint(["request_id"], ["manual_topup_requests.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["identity_users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_reference", name="uq_manual_topup_outbox_event_reference"),
        sa.UniqueConstraint("deduplication_key", name="uq_manual_topup_outbox_deduplication_key"),
    )
    op.create_index(
        "ix_manual_topup_outbox_delivery",
        "manual_topup_notification_outbox",
        ["status", "available_at"],
    )
    op.create_foreign_key(
        "fk_manual_topup_current_receipt",
        "manual_topup_requests",
        "manual_topup_receipts",
        ["current_receipt_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_manual_topup_current_receipt", "manual_topup_requests", type_="foreignkey"
    )
    op.drop_index("ix_manual_topup_outbox_delivery", table_name="manual_topup_notification_outbox")
    op.drop_table("manual_topup_notification_outbox")
    op.drop_table("manual_topup_messages")
    op.drop_table("manual_topup_idempotency")
    op.drop_table("manual_topup_decisions")
    op.drop_index("ix_manual_topup_receipt_hash", table_name="manual_topup_receipts")
    op.drop_table("manual_topup_receipts")
    op.drop_index("ix_manual_topup_review_queue", table_name="manual_topup_requests")
    op.drop_index("ix_manual_topup_customer_status_created", table_name="manual_topup_requests")
    op.drop_table("manual_topup_requests")
