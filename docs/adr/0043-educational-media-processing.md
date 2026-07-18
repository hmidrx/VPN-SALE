# ADR 0043: educational media processing

## Status
Accepted for Milestone 5-F.

## Decision
VPN-SALE implements this capability as a typed, versioned, permission-checked subsystem. Public APIs expose only published, authorized, sanitized projections. Drafts, preview tokens, storage paths, internal notes and infrastructure details are never public. The implementation deliberately excludes VPN panel/provider health, provisioning data, arbitrary executable content, fabricated downloads and invented uptime.

## Consequences
- Business invariants live in domain services and are covered by deterministic tests.
- PostgreSQL stores UUID primary keys, stable codes, immutable publication history and bounded JSON only for typed localized payloads.
- Redis/outbox integration is the publication/cache invalidation boundary for production deployments.
- Rollback and incident corrections preserve history instead of mutating published records.
