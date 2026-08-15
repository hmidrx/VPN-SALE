# ADR 0072: Service activation and customer delivery boundary

Status: proposed for BOT-2B.1

## Context

BOT-2A.1 provisions a deterministic Sanaei global client but deliberately leaves it disabled and without a paid expiry. The local service remains `PENDING_ACTIVATION`, with `starts_at`, `activated_at`, and `expires_at` unset. This prevents provider provisioning or retry time from consuming the purchased duration.

The next boundary must activate the already-created identity, verify the provider state, obtain customer-usable connection links, persist those links safely, and only then make the service customer-visible as `ACTIVE`.

## Decision

Activation is a separate durable worker responsibility, not an extension of CREATE.

A `service_activation_requests` row provides a unique work item per service, bounded retries, a lease owner/expiry, next-attempt scheduling and operator-review terminal state. Claiming uses `FOR UPDATE SKIP LOCKED`; provider I/O happens after the claim transaction commits.

The worker operates only on a `PENDING_ACTIVATION` service with exactly one required attachment in `PROVISIONED/PENDING_DELIVERY` state. Missing or contradictory local state fails closed.

For Sanaei 3x-ui v3.5.0 the certified activation sequence is:

1. authenticate through the already-certified session-cookie transport;
2. `GET /panel/api/clients/get/:email` and verify the deterministic remote UUID;
3. if needed, `POST /panel/api/clients/update/:email` using the authoritative global client object while overriding only `enable`, `totalGB`, `expiryTime`, `limitIp`, deterministic `id` and deterministic `email`;
4. read the client again and require the exact enabled/quota/expiry/device-limit postcondition;
5. `GET /panel/api/clients/links/:email` and validate bounded provider-generated customer URI links.

HTTP success alone is never activation success. An update timeout is ambiguous. A later retry reads first; it does not blindly assume the previous write failed.

## Entitlement clock

The activation attempt computes `activation_at = now` and `expires_at = activation_at + purchased_duration`.

The local paid clock is persisted only in the same database transaction that stores an encrypted delivery payload, verifies the required attachment and transitions the service to `ACTIVE`.

If the provider was activated but the process crashed before the local transaction committed, the retry computes a fresh activation instant. Reconciliation either observes the new desired state or updates the expiry to the fresh activation instant plus the full purchased duration. Therefore the customer does not lose purchased duration during the crash/delivery gap.

## Delivery confidentiality

Provider-generated connection links are sensitive bearer material. Plain links are never persisted. The worker serializes a bounded versioned URI list, hashes the plaintext for integrity checking and encrypts it with the configured identity Fernet key before database persistence in `service_deliveries`.

The authenticated customer delivery endpoint:

- verifies service ownership;
- requires service lifecycle `ACTIVE`;
- requires every required attachment to be `VERIFIED/VERIFIED`;
- requires a `DELIVERED` delivery record;
- requires the configured encryption key version to match the record;
- decrypts and verifies the payload hash and structure;
- returns the links with `private, no-store` response headers.

No provider credentials, panel URLs, cookies or internal allocation identifiers are exposed.

## Failure semantics

Activation failure does not trigger a payment refund. Permanent provider mismatches and exhausted retries move activation to operator review. Configuration/certification problems are retried slowly and remain fail-closed. Ambiguous/transient failures use bounded retry.

A service must never become `ACTIVE` merely because the remote client exists or an update returned HTTP 200.

## Deferred scope

Repository-backed stable subscription tokens, QR convenience UX, Telegram presentation polish, admin activation controls and other provider implementations are intentionally deferred to later BOT-2B increments. Existing public subscription placeholders are not treated as proof of delivery readiness.
