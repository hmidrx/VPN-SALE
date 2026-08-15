# ADR 0071: durable real order fulfillment

## Decision

`order.ready_for_fulfillment.v1` is consumed with a short PostgreSQL lease. Claims use
`FOR UPDATE SKIP LOCKED`, are committed before provider I/O, and stale claims become
eligible after five minutes. Retry timestamps and failure categories are durable and
batches are bounded.

Each order item/unit has one `service_fulfillment_requests` row and one persisted,
deterministic provider identity UUID. The unique item/unit constraint is the database
race arbiter for duplicate outbox deliveries. A nested transaction handles a competing
insert without poisoning the outer event transaction; the winning attempt is then locked.
An active attempt lease makes a second event defer rather than perform provider I/O.

## Certified Sanaei CREATE

The only executable write contract is the exact official MHSanaei/3x-ui `v3.5.0` tag,
release commit `4e928a1ce0945a6e956aa63365034ec24d2b1387`. CREATE is:

- `POST /panel/api/clients/add`
- panel session-cookie authentication
- JSON `ClientCreatePayload` with `client` plus `inboundIds`
- a global client identity which is attached to the selected inbound(s), rather than the
  Alireza-style `/inbounds/addClient/{id}` route family
- a success envelope whose `success` member must be `true`; HTTP success alone is not
  sufficient

The executor reconciles authoritative inventory before CREATE and after every successful,
ambiguous, duplicate/conflict, or deterministic rejection path that could hide a remote
create. A timeout/lost response is never blindly retried. A 409/already-existing style
response is never compensated until authoritative inventory proves the deterministic
remote identity absent. Only then may a definitive rejection become a permanent failure.

Exact version, contract digest and certification gates run before mutation HTTP. Writes
remain disabled by default. Alireza and PasarGuard fail closed until separately certified
executors exist.

## Credentials and configuration failure

Provider credentials use AES-256-GCM with a 96-bit nonce and authenticated AAD binding the
credential kind and panel context. New encryption uses one active `aead-*` key version;
explicit decrypt-only previous AEAD versions support key rotation. Historical pre-AEAD
records are readable only in an explicit migration mode and are rejected by the live write
path. Tamper, wrong-key, wrong-AAD, missing-key, unknown-version and malformed-keyring
conditions fail closed without exposing credential material.

Expected credential/configuration/endpoint failures become `BLOCKED_BY_CONFIGURATION`.
The worker clears the attempt lease and outbox claim immediately, records a durable safe
failure code, schedules bounded retry, and eventually enters operator review. Unexpected
programming exceptions are not relabeled as transient provider failures.

## Authoritative allocation

Runtime allocation does not read `safe_diagnostics` for location, quality, capabilities or
delivery. Revision 0037 adds an explicit typed binding from immutable
`product_version_id + location_code + quality_code` to an allocation target, including the
required capability set. No matching active binding means fail closed. The target must be
a certified Sanaei target with a positive integer inbound and valid configured capacity
(`max_capacity > safety_reserve`). Diagnostics remain diagnostics only.

## Delivery and entitlement clock

This milestone intentionally chooses the pending-delivery option rather than fabricating
a usable subscription/config path. A provider-created remote identity is created disabled
and with no provider expiry. After authoritative reconciliation succeeds, the local service
is `PENDING_ACTIVATION`, `delivery_ready=false`, with a `PROVISIONED/PENDING_DELIVERY`
attachment. No verified delivery attachment, subscription token, config link, or ACTIVE
state is fabricated.

Because the customer cannot use the service before BOT-2B delivery activation, purchased
duration does not begin during provider provisioning. `ServiceModel.starts_at`,
`activated_at` and `expires_at` remain null while delivery is pending. BOT-2B activation
must set provider expiry and the three local timestamps from one activation instant and the
immutable purchased duration. This prevents provisioning or delivery delay from consuming
paid service time.

The private Telegram order projection returns explicit `purchase_state`,
`service_lifecycle` and `delivery_ready`. Customer copy distinguishes PROVISIONING,
provider-created/PENDING_DELIVERY, ACTIVE, REFUNDED and OPERATOR_REVIEW. The bot may show
"service active" only when the repository-backed service lifecycle is ACTIVE and the
authoritative delivery projection is ready; presence of a service reference is never proof
of delivery.

## Failure and financial semantics

Disabled/configuration and recertification outcomes retain the paid order in provisioning
and use bounded retry. Transient and ambiguous results use bounded exponential backoff and
reconciliation precedes retry. Exhausted ambiguous/configuration work enters operator
review and is not refunded as though remote absence were known.

A definitive permanent rejection invokes the shared order compensation service. Its locked
wallet-payment/refund-journal guard makes repeated handling idempotent so a paid order can
produce at most one refund journal. Provider success, local service/attachment creation,
attempt success and outbox completion are committed together; a crash before local
finalization reuses the persisted deterministic remote identity and reconciles before any
new CREATE.

## Operations and rollback

No deployment is part of this change. Enabling real writes requires a separate reviewed
operator action with a migrated AEAD credential, exact live certification evidence and an
authoritative allocation binding. Roll back application code first, leave writes disabled,
then downgrade revision 0037 only after confirming no fulfillment attempts depend on its
identity/retry/binding state. No database reset is required.
