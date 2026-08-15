# ADR 0072 — Service activation and secure customer delivery

## Status

Proposed for BOT-2B.

## Context

BOT-2A.1 deliberately stops after authoritative provider identity creation. The remote identity is disabled, has no purchased expiry, the local service remains `PENDING_ACTIVATION`, and customer-visible entitlement timestamps remain null. Provider creation is therefore not evidence that the customer has a usable service.

BOT-2B must activate that exact remote identity without losing paid duration, fabricate neither provider state nor delivery state, survive lost provider responses, and avoid storing VPN credentials in plaintext database fields or logs.

## Decision

Activation is a separate durable workflow backed by `service_activation_requests`.

A worker claims due activation rows with `FOR UPDATE SKIP LOCKED` and a lease. It never selects a replacement provider target: it must resolve the exact allocation target and remote identity attached by BOT-2A.1.

For certified Sanaei 3x-ui v3.5.0 activation the worker:

1. authenticates using the existing AEAD-protected provider credential path;
2. verifies the original target and remote identity;
3. reads provider-generated client links from the exact tagged `GET /panel/api/clients/links/:email` contract;
4. validates and encrypts the links before the first activation mutation;
5. establishes one durable activation instant and expiry from the immutable paid duration;
6. executes the exact tagged `POST /panel/api/clients/update/:email` full-client update with the original UUID, `enable=true`, paid traffic, paid device limit and durable expiry;
7. reads the client again and requires the exact desired state before declaring provider success;
8. atomically marks the encrypted delivery revision ACTIVE, required attachment VERIFIED, service ACTIVE and activation request SUCCEEDED.

The durable activation instant is reused across retries. A timeout or lost response never creates a new entitlement clock. The provider executor reconciles before another update and treats a verified desired state as success.

## Delivery confidentiality

Provider links are sensitive credentials.

They are stored only inside authenticated encrypted delivery revisions. The database stores ciphertext, encryption key version, a digest and safe metadata. Raw links are not stored in service attachment state, fulfillment state, audit metadata or logs.

Encryption is fail-closed and version-aware. A current key encrypts new revisions; explicitly configured retired keys may decrypt old revisions during controlled rotation. Unknown key versions fail closed.

Customer API delivery requires authoritative ownership, service lifecycle ACTIVE, verified required attachments and an ACTIVE encrypted delivery revision. Sensitive responses are `private, no-store`.

Subscription tokens are opaque and returned in plaintext only at issuance. Persistent token records contain SHA-256 hashes only. Rotation revokes the previous active token. Public subscription reads require the current active hash, active subscription, active service and decryptable active delivery revision.

The Telegram bot obtains credentials only through the existing private service-authenticated bridge and only after an explicit sensitive `OPEN_SUBSCRIPTION` callback. Purchase success text never embeds credentials automatically.

## Failure semantics

Provider authentication/configuration/certification failures block and retry within bounded ceilings. Transient and ambiguous failures retry with bounded backoff. Permanent or exhausted activation moves to operator review.

Activation uncertainty does not automatically refund a paid order because the provider identity may already have been enabled. Reconciliation is required before any compensation decision.

No service is marked ACTIVE and no delivery is exposed unless both provider activation and local encrypted delivery finalization succeed.

## Rollback

Migration `0038_service_activation_delivery` can be downgraded by dropping activation workflow state and encrypted delivery columns. Operators must disable provider writes before rollback so a previous application version cannot create new partially represented activation work while schema rollback is in progress.
