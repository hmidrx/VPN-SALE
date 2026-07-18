
## Milestone 6-D2 fleet operations

Fleet operations add a typed hierarchy for providers, panels, nodes, inbounds and allocation targets; immutable health observations/evaluations; integer capacity snapshots/forecasts; maintenance, drain, evacuation, failover/recovery proposals, bounded bulk operations and typed runbooks. Fleet code orchestrates existing certified application services only and does not call provider transports directly. Customer/reseller exposure remains safe impact-only and never includes credentials, raw provider payloads, panel URLs or infrastructure identifiers.

## Milestone 7-B production release operations
Controlled production rollout uses immutable release plans, separate approvals, change freeze, backup verification, deployment locks, manual canary starts, manual phase advancement, automatic safety pauses, explicit resume, non-destructive rollback, hypercare and reconciliation. Runbooks must record missing production access as `NOT_RUN`/`BLOCKED` and must not claim production success without protected operator evidence.
