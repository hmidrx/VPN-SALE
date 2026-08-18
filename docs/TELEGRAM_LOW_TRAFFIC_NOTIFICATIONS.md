# Telegram low-traffic notifications

Low-traffic notifications are derived only from the durable authoritative usage projection produced by
the certified background usage synchronizer. The notification worker never reads or mutates a VPN
panel.

## Notification stages

- `WARNING`: authoritative usage crosses the normal warning threshold.
- `CRITICAL`: authoritative usage crosses the critical threshold.
- `EXHAUSTED`: two authoritative observations confirm exhaustion (`EXHAUSTED_CONFIRMED`).

`EXHAUSTED_PENDING_CONFIRMATION`, stale usage, missing counters, low-confidence observations and
manual-review states never produce an exhaustion message.

## Anti-spam and recovery behavior

Events are generated only on an upward threshold crossing. Repeated aggregates in the same stage do
not create repeated messages. If a customer buys traffic and the state returns to `AVAILABLE`, a
future crossing can create a new event because it is bound to a new aggregate. A queued message is
revalidated against the latest fresh aggregate immediately before Telegram delivery; recovered or
superseded states are skipped.

The rollout migration marks the latest historical warning/critical/confirmed-exhaustion state as
already processed, preventing a deployment-time flood of old notifications.

## Customer and security boundaries

The existing `low_traffic_enabled` customer preference is authoritative. Delivery also requires a
linked Telegram account, a started bot conversation and a non-blocked bot. Messages expose only the
safe service reference and customer-facing remaining traffic. Provider IDs, remote identities,
credentials, panel diagnostics and reconciliation data never enter the Telegram payload.

The notification button opens the native Telegram service-management screen, where the existing
add-traffic flow is offered only when the service is authoritatively eligible.
