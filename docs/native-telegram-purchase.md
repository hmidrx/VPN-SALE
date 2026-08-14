# Native Telegram purchase

## Architecture

The customer bot reads catalog and pricing data only through the private Telegram API. The API
resolves the Telegram subject to a customer, validates the active product/version and computes a
fresh server-side quote. Confirmation reuses the existing quote, checkout, wallet reservation,
ledger capture, order, invoice, timeline and transactional-outbox implementation. Telegram never
supplies a price or a customer identifier.

The callback carries only a catalog machine code. Redis `ConversationStateV2` stores that code, the
wizard step, an idempotency key and (after confirmation) the customer-safe order reference. State
remains TTL-bound; configuration, credentials, access tokens and provider responses are not stored.

## Lifecycle and failure behavior

A confirmed wallet checkout is reported as accepted/provisioning until fulfillment produces a real
service. The bot does not invent credentials or report success before a service reference exists.
Repeated Telegram updates, rapid confirmation clicks and process restarts reuse the same purchase
idempotency key and therefore the existing durable quote/checkout.

Only fixed plans with exactly one enabled location and quality option are exposed. Custom plans and
plans with selectable options stay hidden rather than silently applying defaults. At confirmation,
the API compares the reviewed selection and price with a newly calculated authoritative quote. A
change returns `RECONFIRM_REQUIRED` without reserving funds, and Telegram requires a second explicit
confirmation. Ambiguous transport results are replayed with the identical mutation key; if the
result remains unknown the bot says so and never claims that the wallet was unchanged.

HTTP 4xx responses are authoritative pre-mutation rejections and are never described as ambiguous.
Transport failures and 5xx responses use same-key reconciliation. Before consulting the live
catalog, confirmation looks up a durable order associated with the customer, external purchase key,
and reviewed revision; a committed purchase therefore wins over later catalog changes. Known review
revisions receive distinct quote child keys, while all retries of one revision resolve to the same
quote and order.

Catalog machine codes are converted to compact opaque Telegram plan references, keeping callback
payloads below Telegram's 64-byte limit even for the longest valid machine code.

Order cancellation uses the existing compensating wallet refund journal for captured payments.
Provider failures must be classified by the fulfillment processor and drive that cancellation path;
the bot renders refunded orders without exposing provider diagnostics.

Historical order screens use `telegram_purchase_display` stored in the immutable order snapshot at
checkout time. They never re-render an old order from the current catalog.

## Security and operations

All routes remain below `/api/v1/internal/telegram`, require the file-mounted bearer credential and
`X-Telegram-Subject`, and perform ownership lookup server-side. Caddy configuration is unchanged.
Amounts are integral rial in commerce and converted to integral toman only at the Telegram boundary.

No migration is required. Rollback consists of reverting the bot callbacks/state fields and private
routes; existing orders remain valid and can continue through the standard fulfillment outbox.
Local startup remains `docker compose up --build` after configuring the documented secret files.

## Known external enablement

This repository baseline emits `order.ready_for_fulfillment.v1` but contains no production order
fulfillment consumer. Panel writes are also deliberately disabled by deployment acknowledgements.
Consequently a real checkout safely remains provisioning on the current test server; live service
creation requires the separately reviewed fulfillment consumer and provider-write enablement. Those
controls are not bypassed here.
