"""Durable service activation and encrypted delivery payloads.

Revision ID: 0038_service_activation_delivery
Revises: 0037_real_fulfillment
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0038_service_activation_delivery"
down_revision: str = "0037_real_fulfillment"
branch_labels = None
depends_on = None

UUID_TYPE = postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "service_activation_requests",
        sa.Column("id", UUID_TYPE, primary_key=True),
        sa.Column(
            "service_id",
            UUID_TYPE,
            sa.ForeignKey("services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fulfillment_request_id",
            UUID_TYPE,
            sa.ForeignKey("service_fulfillment_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(96)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("activation_instant", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("result_code", sa.String(80)),
        sa.Column("failure_category", sa.String(64)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("service_id", name="uq_service_activation_service"),
        sa.UniqueConstraint(
            "fulfillment_request_id", name="uq_service_activation_fulfillment_request"
        ),
    )
    op.create_index(
        "ix_service_activation_status_retry",
        "service_activation_requests",
        ["status", "next_attempt_at", "lease_expires_at"],
    )

    # Existing provider-created services from BOT-2A.1 must converge through the same
    # activation worker. The deterministic UUID makes upgrade retries harmless.
    op.execute(
        """
        insert into service_activation_requests (
            id, service_id, fulfillment_request_id, status, attempt_count,
            created_at, updated_at
        )
        select
            md5('activation:' || s.id::text)::uuid,
            s.id,
            f.id,
            'PENDING',
            0,
            now(),
            now()
        from services s
        join service_fulfillment_requests f on f.service_id = s.id
        where s.lifecycle = 'PENDING_ACTIVATION'
          and f.status = 'SUCCEEDED'
        on conflict (service_id) do nothing
        """
    )

    op.add_column("delivery_revisions", sa.Column("encrypted_payload", sa.Text()))
    op.add_column(
        "delivery_revisions", sa.Column("encryption_key_version", sa.String(64))
    )
    op.add_column("delivery_revisions", sa.Column("payload_sha256", sa.String(80)))


def downgrade() -> None:
    op.drop_column("delivery_revisions", "payload_sha256")
    op.drop_column("delivery_revisions", "encryption_key_version")
    op.drop_column("delivery_revisions", "encrypted_payload")
    op.drop_index("ix_service_activation_status_retry", table_name="service_activation_requests")
    op.drop_table("service_activation_requests")
