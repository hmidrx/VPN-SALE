# ADR 0055: Fleet operations layer

## Status
Accepted

## Context
Milestone 6-D2 needs one operations model for providers, panels, nodes, inbounds, allocation targets, health, capacity, maintenance, drain, evacuation, failover proposals, bulk operations and runbooks without bypassing certified provider/service/migration services.

## Decision
Fleet state is durable PostgreSQL state with immutable observations, snapshots, plans and reports. Health is typed evidence with freshness, confidence and hysteresis; stale or insufficient evidence becomes `UNKNOWN`. Capacity uses non-negative integer accounting and deterministic advisory forecasting. Drain blocks allocation transactionally while evacuation executes only bounded Milestone 6-C2 migration batches. Failover and recovery are proposals requiring approval. Bulk operations and runbooks are allowlisted typed orchestrations with no arbitrary scripts, HTTP, provider commands or SQL.

## Consequences
The console can coordinate fleet operations without exposing infrastructure to customers/resellers or fabricating customer connectivity health. Real staging remains required before enabling provider-specific automation policies.
