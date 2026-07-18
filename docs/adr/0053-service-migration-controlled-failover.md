# ADR 0053: Service migration, controlled failover and attachment history

## Status
Accepted for Milestone 6-C2.

## Context
Production services must move between certified targets without creating a second commercial service, rewriting entitlement history, leaking infrastructure details or bypassing provider write certification.

## Decision
Model migrations as explicit, versioned domain records with typed lifecycle states, immutable source and target snapshots, attachment plans, approvals, capacity reservations, provider-operation references, cutovers, rollback records, reconciliation records, compensation records, failover proposals and orphan remote identity records.

Source and target attachment history is append-only. Credential preservation is allowed only for exact compatible protocol/provider contracts; otherwise pending encrypted credential versions are rotated and activated atomically at cutover. Cross-provider migrations keep separate source and target DTO evidence and never use a universal identity payload. Target capacity is reserved before remote creation and source capacity is retained until verified retirement. Warm migration with bounded dual-active grace is preferred; cold migration, destructive cleanup and source-unreachable failover are high risk. Delivery cutover atomically switches authoritative local projections while preserving the stable subscription URL. Rollback is a bounded operation before source cleanup; after cleanup, operators create a reverse migration. Recovered sources become orphan identities requiring approved reconciliation. Lifetime traffic accounting remains local-authoritative and survives remote counter resets.

## Consequences
Migration workers may create, disable or delete identities only through the Milestone 6-A2B provider-operation engine. Unknown provider versions, stale plan digests, client-supplied infrastructure targets and uncertified writes fail closed. Customer/reseller views expose only safe status, impact and refresh guidance.
