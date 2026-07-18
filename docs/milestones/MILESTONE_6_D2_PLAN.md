# Milestone 6-D2 Plan: Fleet Operations

Milestone 6-D2 adds the production operations layer for certified VPN providers. PostgreSQL is the durable source of truth; Redis/worker memory are lease/cache mechanisms only. Fleet code orchestrates existing provider sync, provisioning, service operations, migration/failover, usage automation, status, notification, audit and Security Center services and never calls provider adapters or raw HTTP transports directly.

## Fleet hierarchy

```mermaid
flowchart TD
  Fleet[Fleet] --> Panel[Provider panel]
  Panel --> Node[Node when provider reports one]
  Panel --> Inbound[Inbound]
  Node --> Inbound
  Inbound --> Target[Allocation target]
  Target --> Attach[Active/pending service attachments]
  Target --> Res[Capacity reservations]
```

Resources preserve provider-specific topology, keep remote identifiers scoped to their panel, retain history when archived, and expose only opaque safe labels to administrators. Customer and reseller APIs show impact only, never panel/node/inbound identifiers.

## Health evidence and limitations

```mermaid
flowchart LR
  Signal[Typed signal] --> Fresh[Freshness check]
  Fresh --> Confidence[Confidence threshold]
  Confidence --> Hysteresis[Consecutive failure/recovery]
  Hysteresis --> State[Effective operational state]
  State --> Proposal[Proposal only, no automatic failover]
```

Health signals include panel API reachability, authentication, TLS, certificate pinning, version, contract, read/write certification, inventory and usage freshness, circuit breaker, node/inbound reported state, drift, ownership conflicts, capacity warnings and worker backlog. Evidence stores source, observed time, freshness window, state, confidence, safe evidence reference and sanitized details only.

Control-plane availability, provider API availability, provider-reported node state, inbound enabled state, customer data-plane connectivity, customer-perceived latency and successful configuration import are explicitly different. This milestone exposes control-plane and provider-reported health only.

## Capacity accounting

```mermaid
flowchart TD
  Hard[Configured hard capacity] --> Effective[Subtract safety, maintenance and stale inventory reserves]
  Active[Active attachments] --> Consumed[Consumed capacity]
  Pending[Pending provisioning reservations] --> Consumed
  Migration[Migration reservations and dual-active] --> Consumed
  Unknown[Uncertain/orphan identity penalty] --> Consumed
  Effective --> Headroom[Available headroom]
  Consumed --> Headroom
```

All authoritative capacity values are non-negative integers. Missing capacity is unknown, not unlimited. Remote identity uncertainty reduces headroom conservatively. Allocation and migration must reserve transactionally and cannot allocate to archived or draining targets.

## Capacity forecasting

```mermaid
flowchart LR
  History[Historical snapshots] --> Enough{Enough data?}
  Enough -->|No| Unknown[No exhaustion date]
  Enough -->|Yes| Rolling[Deterministic rolling average]
  Rolling --> Forecast[Advisory exhaustion horizon]
```

Forecasts use deterministic integer arithmetic over real snapshots. Insufficient data never fabricates an exhaustion date. Forecasts are advisory; allocation still uses current transactional capacity.

## Maintenance and drain

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> VALIDATED
  VALIDATED --> SCHEDULED
  SCHEDULED --> ANNOUNCED
  ANNOUNCED --> PREPARING
  PREPARING --> DRAINING
  DRAINING --> READY
  READY --> IN_PROGRESS
  IN_PROGRESS --> COMPLETED
  IN_PROGRESS --> EXTENDED
  DRAFT --> CANCELLED
  SCHEDULED --> CANCELLED
  IN_PROGRESS --> FAILED
  FAILED --> MANUAL_REVIEW
```

Maintenance uses UTC timestamps, overlap validation, explicit impact, rollback policy and safe notifications. Draining blocks new allocations and migration targets while existing services remain until migration or approved exception.

## Evacuation planning and execution

```mermaid
flowchart TD
  Drain[Drain/critical evidence] --> Snapshot[Freeze service snapshot]
  Snapshot --> Eligibility[Use migration eligibility simulation]
  Eligibility --> Shortfall[Capacity and compatibility analysis]
  Shortfall --> Plan[Immutable plan with expiry]
  Plan --> Approval[Approval]
  Approval --> Batch[Bounded migration batches]
  Batch --> Guardrails{Guardrails OK?}
  Guardrails -->|Yes| C2[Milestone 6-C2 migration]
  Guardrails -->|No| Pause[Pause at safe boundary]
```

Strategies are typed and bounded: low risk first, expiring last, high priority first, balance target headroom, maintain location, maintain provider when possible, and cross-provider only when required. No provider mutation occurs during planning.

## Failover proposal and approval

```mermaid
flowchart TD
  Evidence[Sustained unsafe evidence] --> Proposal[Failover proposal]
  Proposal --> Approval{Separate approval?}
  Approval -->|No| Pending[No migration]
  Approval -->|Yes| Controlled[Convert to controlled evacuation/migration]
```

Signals may create proposals but never execute failover automatically. Self-approval is denied for high-risk actions.

## Recovery proposal

```mermaid
flowchart LR
  Recovered[Fresh recovery evidence] --> Proposal[Recovery proposal]
  Proposal --> Options[Cancel failover / resume maintenance / keep services / reverse migration draft]
  Options --> Approval[Explicit approval]
```

Recovery does not move services back automatically and requires fresh version, contract, health and write-certification evidence.

## Bulk operation execution

```mermaid
flowchart TD
  Select[Explicit references or bounded typed filter] --> Freeze[Freeze target snapshot]
  Freeze --> Dry[Dry validation]
  Dry --> Approve[Approval when required]
  Approve --> Items[Bounded per-item commands]
  Items --> Result[Immutable report with partial failures]
  Result --> Retry[Retry failed eligible items only]
```

Only allowlisted operations are supported. Arbitrary provider commands, remote delete, credential reveal, balance changes and entitlement reductions are forbidden.

## Runbook execution

```mermaid
flowchart TD
  Draft[Typed steps] --> Validate[Registry validation]
  Validate --> Publish[Immutable published version]
  Publish --> Execute[Step-level permission checks]
  Execute --> Confirm{Manual confirmation?}
  Confirm --> Pause[Pause]
  Confirm --> Continue[Continue safe command]
```

Runbooks have no shell, HTTP, Python, JavaScript, SQL, secret access or unregistered provider operation steps.

## Operator procedures

1. Inspect health evidence and freshness before changing allocation state.
2. Schedule maintenance with safe customer/reseller notice.
3. Start drain only after validating capacity and active operations.
4. Simulate evacuation and resolve manual-review blockers.
5. Obtain separate approval for high-risk or cross-provider moves.
6. Execute bounded migration batches and pause on guardrails.
7. Verify source cleanup before releasing capacity.
8. Use recovery proposals after resources recover; do not automatically reverse migrate.

## Real-staging requirements and limitations

Operators must validate provider-specific inventory freshness, capacity identity counts, migration cleanup verification, rate limits, certification invalidation and notification templates against certified staging panels before production enablement. End-to-end VPN connectivity probes are out of scope and must be designed separately before any customer-connectivity health claim.
