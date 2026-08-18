# Telegram authoritative usage sync

The Telegram bot never reads VPN panels during a customer callback. A background worker reads only
certified Sanaei 3x-ui inventory and persists a durable, customer-safe usage projection.

## Authority and safety

- Provider reads use the same endpoint validation, encrypted credential loading, and certified
  Sanaei v3.5.0 contract checks used by the existing production provider integration.
- The worker is read-only and is intentionally independent from `VPN_SALE_PROVIDER_WRITES_ENABLED`.
- Only an active service with exactly one required, verified attachment and an established remote
  identity is eligible until a published multi-attachment aggregation policy is available.
- The local immutable/current service entitlement remains the allowance authority. A panel-reported
  limit is retained only as diagnostic observation data and never silently replaces customer
  entitlement.
- Missing counters, ambiguous remote identity matches, stale aggregates, low-confidence data, and
  unexplained counter decreases fail closed. They never become a fabricated zero or an increased
  remaining balance.
- Customer projections expose only used/remaining/total bytes and synchronization time. Panel IDs,
  remote identities, credentials, contract diagnostics, and provider errors stay internal.

## Freshness

Eligible services are polled no more frequently than every five minutes. Customer-facing usage is
accepted only when the latest provider observation is at most two hours old and has HIGH or MEDIUM
confidence. Otherwise the existing Telegram service screen keeps remaining traffic unknown.

This projection is the prerequisite for Telegram low-traffic lifecycle notifications.
