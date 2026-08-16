# ADR 0072: Service activation and customer delivery boundary

Status: proposed for BOT-2B.1

## Context

BOT-2A.1 provisions a deterministic Sanaei global client but deliberately leaves it disabled and without a paid expiry. The local service remains `PENDING_ACTIVATION`, with `starts_at`, `activated_at`, and `expires_at` unset. This prevents provider provisioning or retry time from consuming the purchased duration.

The next boundary must activate the already-created identity, verify provider state, prove that the platform can render a customer connection from an explicitly published public Delivery Profile, and only then make the service customer-visible as `ACTIVE`.

## Decision

Activation is a separate durable worker responsibility, not an extension of CREATE.

A `service_activation_requests` row provides a unique work item per service, bounded retries, a lease owner/expiry, next-attempt scheduling and operator-review terminal state. Claiming uses `FOR UPDATE SKIP LOCKED`; provider I/O happens after the claim transaction commits.

The worker operates only on a `PENDING_ACTIVATION` service with exactly one required attachment in `PROVISIONED/PENDING_DELIVERY` state. Missing or contradictory local state fails closed.

Before any provider mutation, the activator requires one active `ALLOCATION_TARGET` Delivery Profile assignment for the selected target. The assigned version must be published, valid and protocol-compatible. A customer URI is rendered in memory from that profile and the deterministic remote identity as a precondition. If this cannot be done, provider activation is not attempted.

For Sanaei 3x-ui v3.5.0 the certified activation sequence is:

1. authenticate through the already-certified session-cookie transport;
2. `GET /panel/api/clients/get/:email` and verify the deterministic remote UUID;
3. if needed, `POST /panel/api/clients/update/:email` using the authoritative global client object while overriding only `enable`, `totalGB`, `expiryTime`, `limitIp`, deterministic `id` and deterministic `email`;
4. read the client again and require the exact enabled/quota/expiry/device-limit postcondition.

HTTP success alone is never activation success. An update timeout is ambiguous. A later retry reads first; it does not blindly assume the previous write failed.

## Provider host is not customer-delivery authority

The official Sanaei `GET /panel/api/clients/links/:email` implementation receives the web request host when generating links. A management-panel host is therefore not assumed to be the intended public VPN endpoint.

BOT-2B.1 deliberately does **not** use provider-generated links as customer delivery authority. The platform's published Delivery Profile owns the public address, port, transport, TLS/REALITY fields and renderer compatibility. This keeps the management endpoint separate from the customer data plane and makes CDN/domain/port changes explicit and reviewable.

## Entitlement clock

The activation attempt computes `activation_at = now` and `expires_at = activation_at + purchased_duration`.

The local paid clock is persisted only in the same database transaction that:

- revalidates the current published Delivery Profile assignment;
- proves the customer URI can still be rendered;
- creates an `ACTIVE` `DeliveryRevisionModel` containing only safe profile/attachment metadata and a credential fingerprint;
- marks the required attachment `VERIFIED/VERIFIED`;
- transitions the service to `ACTIVE`.

No customer URI is persisted in the delivery revision.

If the provider was activated but the process crashed before the local transaction committed, the retry computes a fresh activation instant. Reconciliation either observes the fresh desired state or updates expiry to the fresh activation instant plus the full purchased duration. Therefore crash/delivery gap time does not consume the purchased duration before usable delivery.

## Customer delivery

The authenticated customer delivery endpoint:

- verifies service ownership;
- requires service lifecycle `ACTIVE`;
- requires every required attachment to be `VERIFIED/VERIFIED`;
- requires an `ACTIVE` delivery revision;
- verifies the revision attachment, allocation target, renderer version and credential fingerprint;
- renders the URI on demand from the revision's exact Delivery Profile version and current verified remote identity;
- responds with `private, no-store` headers.

A superseded-but-previously-published profile version may continue to render an existing immutable delivery revision. New activations require the currently active published allocation-target assignment.

No provider credentials, management-panel URL, cookies or raw internal allocation metadata are exposed to customers.

## Failure semantics

Activation failure does not trigger a payment refund. Permanent provider mismatches and exhausted retries move activation to operator review. Configuration/certification/profile problems remain fail-closed. Ambiguous/transient failures use bounded retry.

A service must never become `ACTIVE` merely because the remote client exists or an update returned HTTP 200.

## Deferred scope

Repository-backed stable subscription tokens, QR convenience UX, Telegram presentation polish, admin activation/profile-management controls and other provider implementations are intentionally deferred to later BOT-2B increments. Existing public subscription placeholders are not treated as proof of delivery readiness.
