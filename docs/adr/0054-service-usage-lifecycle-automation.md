# ADR 0054: Service usage accounting and lifecycle automation

## Status
Accepted for Milestone 6-D1.

## Decision
VPN-SALE treats provider traffic counters as immutable observations and stores local lifetime usage as append-only positive deltas plus approved corrections. A counter reset, identity recreation or independent migration starts a counter generation; it never erases lifetime usage. Unexpected counter decreases are classified as reset, wrap, recreation, source change, contract mismatch or manual-review anomalies before any destructive lifecycle action.

Aggregation is backend-authoritative and versioned. Shared identities are deduplicated by counter scope, independent identities are summed only under an explicit policy, and migration overlap uses a conservative maximum-per-mirror-group strategy. Stale, partial or low-confidence aggregates block quota enforcement.

Quota and expiry automation creates internal service operations only: `ENFORCE_TRAFFIC_QUOTA`, `ENFORCE_EXPIRY`, `RESTORE_AFTER_TRAFFIC_ADDON`, `RESTORE_AFTER_RENEWAL` and `RECONCILE_REMOTE_ENFORCEMENT`. Remote mutation remains delegated to the Milestone 6-C1 service-operation platform and Milestone 6-A2B provider-operation engine.

Threshold notifications use a deterministic deduplication scope: service, cycle, policy, version, threshold code, direction and generation. Messages contain only safe service labels, remaining usage/time and opaque operation links.

Workers are PostgreSQL-backed, leased, bounded by indexed batches, rate-limit aware and safe for duplicate delivery. Raw observations have bounded retention; rollups and lifetime checkpoints are retained longer.

## Consequences
- Unknown traffic is not zero, unlimited traffic is not zero, and unknown expiry is not unlimited.
- Provider-specific semantics for Sanaei, Alireza and PasarGuard remain documented and normalized before application code consumes them.
- Corrections are append-only, permissioned and audited; high-risk corrections require separate approval.
