# ADR 0051: Delivery Profile and canonical configuration delivery

## Status
Accepted for Milestone 6-B2.

## Decision
VPN-SALE owns delivery profiles, canonical resolved connections, renderer versions, subscription tokens and QR generation. Provider panel share links are never authoritative. Published Delivery Profile versions and delivery revisions are immutable and store no plaintext credential or complete rendered output.

## Rationale
Service provisioning verifies remote identities but does not provide safe customer configuration. A store-owned canonical model lets the platform validate public address, Host, SNI, transport/security and compatibility before revealing credentials.

## Consequences
- Profile resolution precedence is deterministic and ambiguous matches block rendering.
- Renderers accept only canonical resolved connections.
- Subscription URLs are opaque path tokens, hashed at rest, revocable and no-store.
- Secret-bearing HTTP responses, QR, audit and metrics have explicit redaction boundaries.
- Customer and reseller delivery authorization remains backend authoritative.
