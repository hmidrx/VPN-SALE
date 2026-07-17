# ADR 0023: Versioned payment adapters, webhook inbox and secret boundaries

## Status
Accepted for Milestone 4-A1.

## Decision
Payment methods reference provider code and adapter version. The adapter registry is explicit and fails closed for unknown versions. Fake adapters are allowed only in test/development registry contexts and are rejected in production. Payment method rows store only secret references plus credential state/version; APIs never expose credentials.

Webhook ingestion stores a digest, provider event reference, signature result, sanitized headers and safe metadata. Raw bodies and signature headers are not API data. Replay protection is enforced with provider event and digest uniqueness.

## Consequences
Multiple future gateway instances and versions can coexist without dynamic code loading or provider-specific core tables.

## Milestone 4-A2B1 note
Administrator payment operations are represented in admin-web as a safe operations console for payment methods, intents, attempts, verifications, settlements and webhook inbox records. The console preserves payment immutability, credential boundaries, backend-authoritative authorization, no browser persistence for payment data, sanitized webhook rendering, and no refund/reconciliation-repair or real-gateway scope.
