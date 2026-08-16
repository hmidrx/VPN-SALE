# BOT-3C — Durable support reply notifications

BOT-3C consolidates support delivery around the durable PostgreSQL support runtime introduced before this milestone. The former in-memory FastAPI support module is removed and its customer, reseller, and administrator routes are no longer mounted in production.

## Durable notification flow

1. A public support-agent message is inserted into `support_messages`.
2. Migration `0040_support_reply_notifications` installs an `AFTER INSERT` trigger that creates one `support_reply_notification_outbox` row when the message is an `AGENT_MESSAGE`, is `PUBLIC`, and belongs to a `CUSTOMER` conversation.
3. The outbox stores only identifiers and delivery state. It does not duplicate the support reply body or ticket subject.
4. `SupportReplyDeliveryWorker` claims eligible rows with `FOR UPDATE SKIP LOCKED`, including stale `PROCESSING` rows after the lease timeout.
5. Before delivery, the worker verifies the conversation/message relationship, customer ownership, public visibility, Telegram account state, and the customer's `support_reply_enabled` preference.
6. Telegram delivery happens outside the database transaction. Temporary transport failures are retried with bounded exponential backoff; terminal or intentionally skipped outcomes are persisted explicitly.

Internal notes never create notification events. Existing support replies are not backfilled during the migration; only messages inserted after `0040` is applied are eligible.

## Customer destination

Notifications deep-link to the existing customer-web `/support?source=telegram` surface. The Telegram text contains only a generic new-reply notice and the support reference; the actual reply remains in the durable support store.

## Operational controls

The worker reuses the existing notification process and environment contract:

- `VPN_SALE_DATABASE_URL`
- `VPN_SALE_BOT_ENABLED`
- `VPN_SALE_TELEGRAM_BOT_TOKEN`
- `VPN_SALE_PUBLIC_APP_ORIGIN`

No additional daemon or secret is introduced. When bot delivery is disabled, the event is marked `SKIPPED` rather than performing a network call.

## Delivery outcomes

Safe outcome categories include:

- `BOT_DISABLED`
- `UNLINKED`
- `BOT_NOT_STARTED`
- `BOT_BLOCKED`
- `PREFERENCE_DISABLED`
- `INVALID_EVENT_DATA`
- `TELEGRAM_TEMPORARY`
- `MAX_ATTEMPTS`

Logs contain the opaque event reference, attempt count, safe status, and correlation identifier only; message bodies and ticket subjects are not logged by this worker.

## Rollback

Downgrading migration `0040_support_reply_notifications` removes the trigger, trigger function, indexes, and outbox table. The durable support messages themselves are not modified by the rollback.

Because the old in-memory runtime is intentionally removed from application code, rolling back only the database migration does not restore those legacy routes. Restoring the obsolete runtime would require reverting the BOT-3C application commits and is not a supported production recovery path.
