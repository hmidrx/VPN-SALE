# Milestone 6-A2A plan — provider write safety gate

Date: 2026-07-18.

## Verified compatibility targets

- `MHSanaei/3x-ui` tag `v3.5.0`, release commit `4e928a1`.
- `alireza0/x-ui` tag `v1.11.3`, release commit `419fce7`.
- `PasarGuard/panel` tag `v4.0.2`, release commit `0b0ddaa`.

## Scope

Milestone 6-A2A corrects merged provider contract metadata, especially invalid PasarGuard v5.1.0 assumptions, and adds a contract-only mutation layer: typed provider-neutral commands, provider-specific write operation records, mutation preflight, sanitized dry-run plans, postconditions, compensation policy, idempotency/concurrency states, write-readiness evidence and deterministic mock-contract tests. Real provider writes remain disabled and return `PROVIDER_WRITE_NOT_ENABLED`.

## PasarGuard corrections

- Target changed from unsupported `v5.1.0` to official `v4.0.2`.
- API-key and generated OpenAPI claims are removed.
- Panel administrator session credentials are separated from node/node-bridge credentials.
- PasarGuard users are modeled as panel user aggregates, not X-UI inbound clients.
- Incorrect read certifications based on the old digest require recertification.

## Safety gates

Preflight validates exact version, digest, read certification, credentials, panel status, operation support, idempotency conflict, remote snapshot freshness and compensation/read-after-write definitions without transport writes. Dry-run plans expose only sanitized endpoint identifiers, postconditions, evidence, warnings and immutable plan digests; they never expose raw payloads, cookies, API keys, UUID/password material or full URLs.

## Future canary procedure

Use a dedicated staging panel and disposable inbound/template, create one tagged canary identity, read/verify, update one field, read/verify, disable/enable, reset traffic, delete, then verify cleanup and unrelated-resource integrity. Production panels are forbidden as initial write-certification targets.
