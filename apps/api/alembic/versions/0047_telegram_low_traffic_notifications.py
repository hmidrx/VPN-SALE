"""Baseline existing low-traffic states before proactive Telegram delivery.

Revision ID: 0047_low_traffic_tg
Revises: 0046_service_op_tg_notify
Create Date: 2026-08-18
"""

from __future__ import annotations

from alembic import op

revision: str = "0047_low_traffic_tg"
down_revision: str = "0046_service_op_tg_notify"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # Existing authoritative warning/critical/exhausted states predate proactive
    # traffic delivery. Mark only the latest historical aggregate per account as
    # processed so rollout cannot flood customers. A later transition receives a
    # different aggregate-bound event key and remains eligible for delivery.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                aggregate.id,
                aggregate.usage_account_id,
                aggregate.quota_state,
                aggregate.calculated_at,
                row_number() OVER (
                    PARTITION BY aggregate.usage_account_id
                    ORDER BY aggregate.calculated_at DESC, aggregate.id DESC
                ) AS row_number
            FROM service_usage_aggregates AS aggregate
        ), latest AS (
            SELECT
                ranked.id,
                ranked.usage_account_id,
                ranked.quota_state,
                ranked.calculated_at,
                CASE
                    WHEN ranked.quota_state = 'WARNING' THEN 'WARNING'
                    WHEN ranked.quota_state = 'CRITICAL' THEN 'CRITICAL'
                    WHEN ranked.quota_state = 'EXHAUSTED_CONFIRMED' THEN 'EXHAUSTED'
                    ELSE NULL
                END AS stage
            FROM ranked
            WHERE ranked.row_number = 1
              AND ranked.quota_state IN ('WARNING', 'CRITICAL', 'EXHAUSTED_CONFIRMED')
        )
        INSERT INTO transactional_outbox (
            id,
            event_key,
            event_type,
            status,
            payload,
            attempt_count,
            available_at,
            claimed_at,
            processed_at,
            failure_category
        )
        SELECT
            md5('tg-svc-traffic-baseline:' || latest.id::text || ':' || latest.stage)::uuid,
            'tg-svc-traffic:' || latest.id::text || ':' || latest.stage,
            'service_traffic.telegram_notification.v1',
            'PROCESSED',
            jsonb_build_object(
                'usage_account_id', latest.usage_account_id::text,
                'aggregate_id', latest.id::text,
                'stage', latest.stage,
                'baseline', true
            ),
            0,
            latest.calculated_at,
            NULL,
            CURRENT_TIMESTAMP,
            'BASELINED'
        FROM latest
        ON CONFLICT (event_key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Preserve runtime notifications and remove only rows owned by this rollout baseline.
    op.execute(
        """
        DELETE FROM transactional_outbox
        WHERE event_type = 'service_traffic.telegram_notification.v1'
          AND status = 'PROCESSED'
          AND failure_category = 'BASELINED'
          AND payload ->> 'baseline' = 'true'
          AND id = md5(
              'tg-svc-traffic-baseline:' || (payload ->> 'aggregate_id') || ':' ||
              (payload ->> 'stage')
          )::uuid
        """
    )
