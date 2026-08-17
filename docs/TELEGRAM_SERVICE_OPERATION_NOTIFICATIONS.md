# Telegram paid service-operation notifications

This increment adds proactive Telegram delivery for terminal outcomes of the existing customer-native `RENEW` and `ADD_TRAFFIC` flows.

## Scope

- A paid customer operation that reaches a terminal state is projected into the existing transactional outbox with a deterministic key derived from operation ID and terminal status.
- The worker sends one Persian Telegram message for that state and includes a native `SERVICE_OPERATION_STATUS` callback button (`b:v1:svst:<operation-reference>`).
- The button reuses the authoritative customer-scoped status endpoint and bot renderer already used by manual status tracking. It does not open the Mini App.
- Success, partial application, uncertain result, compensation-required/compensated, manual-review, failure, cancellation and expiry states have distinct safe customer messages.
- Intermediate execution/reconciliation states are intentionally not pushed to avoid notification spam; the existing status action remains available for active polling.

## Ownership and financial safety

Notification eligibility requires all of the following:

- operation type is `RENEW` or `ADD_TRAFFIC`;
- requester type is `CUSTOMER`;
- the direct service-operation payment belongs to the same customer;
- the service beneficiary is the same customer;
- payment is already `CAPTURED` or `REFUNDED`;
- operation is already in a terminal state.

The notification worker is read-only with respect to wallet, ledger, service state and provider state. It does not reserve, capture, refund or otherwise mutate money, and it never executes provider operations. Error/review messages tell the customer not to repeat payment while the authoritative state needs attention.

The existing `payment_enabled` notification preference controls these paid-operation outcome messages. Delivery is also skipped when the bot is disabled, the Telegram identity is not linked, the bot has not been started, or the bot is known to be blocked.

## Delivery and retry behavior

The worker uses the existing `transactional_outbox` table. Event keys have the form:

```text
tg-svc-op:<operation-id>:<terminal-status>
```

This makes delivery generation idempotent per terminal state. Claims use `FOR UPDATE SKIP LOCKED`, Telegram I/O happens outside the database transaction, and transient Telegram failures use the existing bounded exponential retry policy. A permanently exhausted or invalid notification is marked failed without changing the underlying service operation.

No provider IDs, credentials, configuration links, reconciliation snapshots, wallet internals or adapter diagnostics are included in the Telegram message.

## Rollout baseline

Migration `0046_service_op_telegram_notifications` inserts deterministic `PROCESSED` baseline outbox rows for terminal paid operations that already exist when the migration runs. This prevents deployment from sending stale historical notifications.

The baseline key includes both operation ID and its current terminal status. If an operation legitimately moves later to a different terminal status, that new status receives a different event key and can generate a fresh notification.

Downgrade removes only migration-owned baseline rows (`baseline=true`, `failure_category=BASELINED`). Runtime notification records are intentionally preserved so rollback/redeploy cannot accidentally erase delivery history and cause duplicate sends.

## Rollback

The runtime worker can be disabled with the existing `VPN_SALE_BOT_ENABLED=false` control, which stops Telegram delivery without changing financial or provider state. Reverting this code removes the notification worker from the process. If the migration is downgraded, only its historical baseline rows are deleted; runtime-generated delivery history remains intact.
