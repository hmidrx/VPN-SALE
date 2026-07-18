# Milestone 6-C2 Plan: Production service migration and controlled failover

## Scope
Milestone 6-C2 adds controlled migration of an existing service attachment or complete service across inbounds, nodes, panels, certified providers, allocation pools and delivery profile versions. It does **not** create a new commercial service, change payer attribution, rewrite orders/invoices/payments, expose raw infrastructure to customers, or perform unattended mass failover.

## Lifecycle
```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> CHECKING_ELIGIBILITY
  CHECKING_ELIGIBILITY --> SIMULATED
  SIMULATED --> AWAITING_APPROVAL
  AWAITING_APPROVAL --> APPROVED
  APPROVED --> RESERVING_TARGET
  RESERVING_TARGET --> PREPARING_TARGET
  PREPARING_TARGET --> PROVISIONING_TARGET
  PROVISIONING_TARGET --> VERIFYING_TARGET
  VERIFYING_TARGET --> READY_FOR_CUTOVER
  READY_FOR_CUTOVER --> CUTTING_OVER
  CUTTING_OVER --> DUAL_ACTIVE_GRACE
  CUTTING_OVER --> TARGET_ACTIVE
  DUAL_ACTIVE_GRACE --> RETIRING_SOURCE
  TARGET_ACTIVE --> RETIRING_SOURCE
  RETIRING_SOURCE --> VERIFYING_SOURCE_RETIREMENT
  VERIFYING_SOURCE_RETIREMENT --> COMPLETED
  PROVISIONING_TARGET --> PARTIALLY_APPLIED
  PARTIALLY_APPLIED --> RECONCILING
  READY_FOR_CUTOVER --> ROLLBACK_PENDING
  DUAL_ACTIVE_GRACE --> ROLLBACK_PENDING
  ROLLBACK_PENDING --> ROLLING_BACK
  ROLLING_BACK --> ROLLED_BACK
```

Every transition validates current status, actor permission, optimistic version and immutable plan digest, then emits audit/outbox work from the application layer.

## Eligibility and target selection
```mermaid
flowchart TD
  A[Admin request] --> B[Load service and immutable entitlement]
  B --> C[Check active operations and migrations]
  C --> D[Reconcile source snapshot]
  D --> E[Run allocation engine]
  E --> F[Filter write-certified targets]
  F --> G[Check delivery profile compatibility]
  G --> H[Return sanitized candidates]
```
Eligibility performs no remote mutation and returns typed outcomes such as `ELIGIBLE`, `SOURCE_UNCERTAIN`, `TARGET_CAPACITY_UNAVAILABLE`, `RECERTIFICATION_REQUIRED` or `CONFLICTING_OPERATION`.

## Target reservation
```mermaid
sequenceDiagram
  participant API
  participant DB
  participant Worker
  API->>DB: validate plan digest and policy
  Worker->>DB: lock migration and target capacity rows
  Worker->>DB: create one reservation per target attachment
  Worker->>DB: renew leases while active
  Worker->>DB: convert target allocation only after cutover
  Worker->>DB: release source only after verified retirement
```
During dual-active grace, both source and target consume capacity.

## Credential preservation and rotation
```mermaid
flowchart TD
  A[Compare source protocol and target contract] --> B{Same semantics and explicit set supported?}
  B -->|yes| C[Preserve encrypted credential version]
  B -->|no| D[Generate pending credential]
  D --> E[Encrypt outside migration records]
  E --> F[Provision target]
  F --> G[Verify fingerprint]
  G --> H[Activate only at cutover]
```
Credentials are never blindly converted between protocols and plaintext never enters migration records, logs, audit, metrics or browser storage.

## Warm migration
```mermaid
sequenceDiagram
  participant Source
  participant Target
  participant Delivery
  Source->>Source: reconcile authoritative state
  Target->>Target: provision via A2B provider-operation engine
  Target->>Target: read-after-write verify
  Delivery->>Delivery: prepare pending revision
  Delivery->>Delivery: atomic cutover
  Source->>Source: bounded grace
  Source->>Source: disable/detach/delete per policy
```

## Atomic delivery cutover
```mermaid
flowchart LR
  A[Verified target] --> B[Validate plan digest]
  B --> C[Check no newer service operation]
  C --> D[DB transaction]
  D --> E[Active attachments]
  D --> F[Allocation snapshot]
  D --> G[Credential versions]
  D --> H[Delivery revision]
  H --> I[Stable subscription token serves new content]
```
No provider HTTP call occurs inside the cutover transaction.

## Dual-active grace and source retirement
```mermaid
flowchart TD
  A[Cutover committed] --> B[Bounded grace]
  B --> C[Re-read source]
  C --> D{Ownership verified?}
  D -->|no| E[Manual review]
  D -->|yes| F[Disable source]
  F --> G[Verify disabled]
  G --> H[Detach/delete only if safe]
  H --> I[Release source capacity]
```

## Controlled failover
```mermaid
flowchart TD
  A[Health/security/maintenance evidence] --> B[FailoverProposal]
  B --> C[Explicit authorization]
  C --> D[Stronger approval if cross-provider or source unreachable]
  D --> E[Reserve target]
  E --> F[Provision and verify target]
  F --> G[Cut over]
  G --> H[Record possible old-source activity]
  H --> I[Create orphan reconciliation if source unreachable]
```
Health events may propose failover but never execute it automatically.

## Rollback
```mermaid
flowchart TD
  A[Rollback request] --> B{Within safe window?}
  B -->|no| C[Reverse migration required]
  B -->|yes| D{Cutover committed?}
  D -->|no| E[Clean target and leave source authoritative]
  D -->|yes| F[Verify source and no newer operation]
  F --> G[Cut delivery back atomically]
  G --> H[Retire target]
```
Rollback never rewrites history and cannot silently overwrite newer service operations.

## Orphan-source reconciliation
```mermaid
flowchart TD
  A[Recovered source observed] --> B[Compare ownership evidence]
  B --> C{Matches migrated service?}
  C -->|no| D[Unknown resource: manual review]
  C -->|yes| E[OrphanedRemoteIdentity]
  E --> F[Approval required]
  F --> G[Disable/delete through A2B]
  G --> H[Verify absence before capacity release]
```

## APIs and UI
Administration APIs provide eligibility, simulation, draft creation, approval, reservation, execution, cutover, cleanup, rollback, reconciliation, failover proposals and orphan cleanup review. Customer/reseller APIs expose only safe migration state and delivery refresh guidance. The admin console adds RTL routes for service migrations, failover proposals and orphaned identities.

## Known provider limitations
Only certified provider contracts may be used. Cross-provider credential preservation is blocked unless exact protocol identity semantics and target write contracts support setting the same credential. Provider-specific unsupported device/IP/HWID semantics block migration or require explicit policy approval.
