# Telegram service expiry reminders

## Goal

Notify an eligible Telegram customer before an ACTIVE service expires without requiring the website or Mini App.

## Reminder windows

The worker emits at most one reminder for each expiry cycle and reminder stage:

- `72H`: when more than 24 hours and at most 72 hours remain.
- `24H`: when more than 0 hours and at most 24 hours remain.

Urgent 24-hour reminders are claimed before 72-hour reminders. Expired services are not backfilled or notified by this increment, which avoids a rollout flood for historical services.

## Durable deduplication

Each reminder is persisted through the existing `transactional_outbox` with an event key bound to:

- service id,
- reminder stage,
- the exact UTC expiry snapshot to second precision.

A later renewal changes the expiry snapshot and therefore creates a new future reminder cycle. Non-expiry service changes do not create duplicate expiry reminders.

## Delivery safety

Before Telegram I/O the worker revalidates that:

- the service still exists,
- the service is still `ACTIVE`,
- the service has not expired,
- the current expiry still matches the queued expiry snapshot,
- a delayed 72-hour reminder has not already entered the 24-hour window,
- the Telegram account is linked, started and not blocked,
- the customer has not disabled `service_expiry_enabled`.

Stale reminders are marked processed and skipped rather than delivered. Telegram failures use the existing bounded retry policy and stale claims are recoverable.

## Native Telegram action

The notification button uses the existing compact `OPEN_SERVICE` callback (`b:v1:svc_open:<reference>`). It never opens the website or Mini App. The service-management screen remains backend-authoritative and decides whether renewal is currently eligible.

## Scope

This increment does not:

- debit wallets,
- mutate providers,
- renew services automatically,
- change website or app UI,
- add low-traffic notifications.

Low-traffic alerts should be implemented separately once an authoritative usage snapshot is available for the active service.