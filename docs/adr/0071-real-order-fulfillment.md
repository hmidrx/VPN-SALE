# ADR 0071: durable real order fulfillment

## Decision

`order.ready_for_fulfillment.v1` is consumed with a short PostgreSQL lease. Claims use
`FOR UPDATE SKIP LOCKED`, are committed before provider I/O, and stale claims become
eligible after five minutes. Retry timestamps and failure categories are durable and
batches are bounded.

Each order item/unit has one `service_fulfillment_requests` row and one persisted,
deterministic provider identity UUID. The unique item/unit constraint prevents parallel
economic identities. A provider executor must reconcile inventory before CREATE and
again after CREATE, so a lost response or crash never causes a blind second mutation.

Only the certified Sanaei 3x-ui v3.5.0 CREATE contract has an execution implementation.
It requires an explicit configured inbound, exact certification/preflight success,
credential-vault resolution, TLS validation, authenticated session transport, bounded
timeouts, and authoritative read-after-write verification. Alireza and PasarGuard fail
closed until separately certified executors exist.

Provider writes remain disabled by default in Compose. Disabled/configuration and
recertification outcomes retain paid orders in provisioning and retry after six hours;
they never fabricate a service. Transient and ambiguous results are scheduled with
bounded exponential backoff and reconciliation precedes any retry. Durable attempt
ceilings move exhausted work to operator review without refunding ambiguous creates.
Definitive permanent rejection invokes the shared authoritative order compensation
service, whose locked wallet payment and refund-journal guard make retries idempotent.

On verified success, service creation, fulfillment/order success, and outbox completion
are one transaction. Unique service and attempt constraints make crashes after local
creation converge without duplicates. The immutable order-item snapshot is copied into
the entitlement, so catalog edits cannot alter purchased traffic, duration, devices,
location, or quality. A verified attachment and token-issuance-ready delivery subscription
are created before a service becomes ACTIVE; otherwise it stays PENDING_ACTIVATION.
Sensitive remote identity and delivery values are never logged.

When `VPN_SALE_PROVIDER_WRITES_ENABLED=true`, worker composition selects an eligible
Sanaei allocation target from the immutable purchased location/quality, resolves the
latest panel credential through the provider vault, loads certification evidence,
validates the endpoint/TLS policy, authenticates, executes certified preflight/CREATE,
and always closes the authenticated client. The disabled provisioner is used only when
the flag is explicitly false.

## Operations and rollback

Run the worker normally; enabling real writes requires a reviewed deployment change and
live panel certification evidence. Roll back application code first, leave writes
disabled, then downgrade revision 0037 only after confirming no fulfillment attempts
depend on its identity/retry columns. No database reset is required.

## Production-path audit

The completion audit found only the expected outbox/order event names, the existing
customer service operation projection's truthful empty eligible-operation list, and
the explicitly test-only `FakePanelProvider`. No TODO, FIXME, placeholder,
`NotImplemented`, dry-run-only mutation, disabled-write fake success, or production
`return False` path remains in the audited fulfillment/write modules.
