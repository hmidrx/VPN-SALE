"""Baseline paid service operations before Telegram terminal notifications.

Revision ID: 0046_service_op_telegram_notifications
Revises: 0045_service_op_wallet_payment
Create Date: 2026-08-17
"""

from __future__ import annotations

from alembic import op

revision: str = "0046_service_op_telegram_notifications"
down_revision: str = "0045_service_op_wallet_payment"
branch_labels: None = None
depends_on: None = None

_EVENT_TYPE = "service_operation.telegram_notification.v1"


def upgrade() -> None:
    # Existing completed/failed paid operations predate proactive Telegram delivery.
    # Mark only those historical terminal states as already processed so rollout
    # cannot flood customers with stale notifications. Later status transitions use
    # a different event_key and remain eligible for a fresh notification.
    op.execute(
        f"""
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
            md5(
                'tg-svc-op-baseline:' || operation.id::text || ':' || operation.status
            )::uuid,
            'tg-svc-op:' || operation.id::text || ':' || operation.status,
            '{_EVENT_TYPE}',
            'PROCESSED',
            jsonb_build_object(
                'operation_id', operation.id::text,
                'terminal_status', operation.status,
                'baseline', true
            ),
            0,
            operation.updated_at,
            NULL,
            CURRENT_TIMESTAMP,
            'BASELINED'
        FROM service_operations AS operation
        JOIN service_operation_payments AS payment
          ON payment.operation_id = operation.id
        JOIN services AS service
          ON service.id = operation.service_id
        WHERE operation.requester_type = 'CUSTOMER'
          AND operation.operation_type IN ('RENEW', 'ADD_TRAFFIC')
          AND operation.status IN (
              'SUCCEEDED',
              'PARTIALLY_APPLIED',
              'FAILED',
              'UNCERTAIN',
              'COMPENSATION_REQUIRED',
              'COMPENSATED',
              'MANUAL_REVIEW',
              'CANCELLED',
              'EXPIRED'
          )
          AND payment.status IN ('CAPTURED', 'REFUNDED')
          AND payment.customer_id = service.beneficiary_customer_id
          AND operation.requester_id = payment.customer_id::text
        ON CONFLICT (event_key) DO NOTHING
        """
    )


def downgrade() -> None:
    # Remove only rows owned by this migration. Notifications created by the
    # runtime after rollout are intentionally preserved.
    op.execute(
        f"""
        DELETE FROM transactional_outbox
        WHERE event_type = '{_EVENT_TYPE}'
          AND status = 'PROCESSED'
          AND failure_category = 'BASELINED'
          AND payload ->> 'baseline' = 'true'
          AND id = md5(
              'tg-svc-op-baseline:' || payload ->> 'operation_id' || ':' ||
              payload ->> 'terminal_status'
          )::uuid
        """
    )
