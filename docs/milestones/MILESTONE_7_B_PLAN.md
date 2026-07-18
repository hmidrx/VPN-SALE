# Milestone 7-B plan: controlled production rollout

Milestone 7-B implements the release-control platform for production-style rollout without performing a real production launch. Normal CI and Codex runs cannot deploy, access production secrets, enable real payments, register real provider credentials, select real customers, migrate real customers or mark launch success. Missing production access remains `NOT_RUN`, `BLOCKED` or `EXPIRED`.

Provider target compatibility was rechecked on 2026-07-18 against official GitHub release listings: MHSanaei/3x-ui `v3.5.0`, alireza0/x-ui `v1.11.3`, and PasarGuard/panel `v4.0.2` remain the certified target names from Milestone 7-A1. No certified target is changed by this milestone.

## Domain scope

The domain model adds typed production release plans, immutable plan versions bound to one finalized Release Candidate, artifacts, preflight gates, approvals, phase policies, cohorts, provider production certification, health pause/resume, rollback types, reconciliation outcomes and sanitized final reports.

Required gates are evaluated independently: `NOT_RUN`, `PASSED`, `PASSED_WITH_LIMITATIONS`, `FAILED`, `BLOCKED`, and `EXPIRED` are visible states. No aggregate ready flag may hide failed or missing evidence.

## Lifecycle

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> PREFLIGHT_FAILED: missing/stale gate
  DRAFT --> READY_FOR_APPROVAL: all required gates pass
  READY_FOR_APPROVAL --> AWAITING_APPROVAL: requester submits
  AWAITING_APPROVAL --> APPROVED: separate approvers
  APPROVED --> CHANGE_FREEZE
  CHANGE_FREEZE --> BACKUP_VERIFIED
  BACKUP_VERIFIED --> DEPLOYING: typed confirmation
  DEPLOYING --> CANARY_PENDING: smoke verified
  CANARY_PENDING --> CANARY_RUNNING: explicit start
  CANARY_RUNNING --> CANARY_PAUSED: critical gate
  CANARY_PAUSED --> CANARY_RUNNING: reviewed resume
  CANARY_RUNNING --> PROGRESSIVE_ROLLOUT: explicit advance
  PROGRESSIVE_ROLLOUT --> ROLLOUT_PAUSED: critical gate
  PROGRESSIVE_ROLLOUT --> HYPERCARE: explicit review
  PROGRESSIVE_ROLLOUT --> ROLLING_BACK: rollback command
  ROLLING_BACK --> ROLLED_BACK
```

## Production preflight

```mermaid
flowchart TD
  RC[Finalized RC] --> Digest[Artifact and schema digest match]
  Digest --> Evidence[CI/load/security/restore evidence]
  Evidence --> Env[Production config, secrets presence, DNS/TLS]
  Env --> Provider[Production provider certification]
  Provider --> Gates{Every required gate?}
  Gates -->|NOT_RUN/BLOCKED/FAILED/EXPIRED| NoGo[PREFLIGHT_FAILED]
  Gates -->|PASSED or limitations| Approval[READY_FOR_APPROVAL]
```

## Approval separation

```mermaid
sequenceDiagram
  participant R as Requester
  participant A as Release approver
  participant D as Deployment approver
  participant S as Security approver
  R->>R: create immutable plan version
  R->>A: request approval
  A-->>R: approve if not requester
  D-->>R: approve deployment role
  S-->>R: approve security role
  R->>R: APPROVED only after required distinct approvals
```

## Deployment orchestration

```mermaid
flowchart LR
  Validate[Validate plan/RC/environment] --> Freeze[Verify change freeze]
  Freeze --> Backup[Verify recent encrypted backup]
  Backup --> Lock[Acquire deployment lock]
  Lock --> Artifact[Deploy immutable artifacts]
  Artifact --> Migration[Run migrations once]
  Migration --> Smoke[Startup/readiness/smoke]
  Smoke --> Evidence[Deployment evidence]
  Evidence --> Wait[Wait for explicit canary start]
```

The GitHub workflow is opt-in `workflow_dispatch`, bound to the `production` environment, requires typed confirmation, requests no secrets by default and reports blocked when no external protected production runner is configured.

## Canary phases and cohort selection

```mermaid
flowchart TD
  Policy[Typed phase policy] --> Eligibility[Typed eligibility checks]
  Eligibility --> Hash[HMAC keyed deterministic bucket]
  Hash --> Bounds[Maximum cohort size]
  Bounds --> Snapshot[Immutable phase snapshot]
  Snapshot --> Exposure[Backend-authoritative exposure]
```

Phases include deployment smoke, synthetic internal, staff, provider canary, allowlisted customer, percentage phases and full exposure. Real-customer canary remains disabled by default and requires separate approval.

## Health-gate pause and resume

```mermaid
flowchart TD
  Metrics[Fresh health evidence] --> Critical{Critical failure/stale?}
  Critical -->|yes| Pause[Pause exposure and create incident/manual review]
  Critical -->|no| Complete[Phase may be complete]
  Pause --> Repair[Root cause and refreshed evidence]
  Repair --> Approval[Explicit resume approval]
  Approval --> Resume[Resume same plan/version]
```

## Rollback and service reconciliation

```mermaid
flowchart TD
  Regression[Detected regression] --> Type{Rollback type}
  Type --> Feature[Feature/config rollback]
  Type --> App[Application artifact rollback]
  App --> Schema{Schema compatible?}
  Schema -->|no| ForwardFix[FORWARD_FIX_REQUIRED]
  Schema -->|yes| DeployPrior[Deploy verified prior artifact]
  DeployPrior --> Preserve[Preserve orders, ledger, services, provider identities]
  Preserve --> Reconcile[Create repair/manual review for uncertain effects]
```

## Hypercare and completion report

```mermaid
flowchart LR
  Initial[Initial hypercare] --> Extended[Extended if blockers]
  Extended --> Exit[Exit review]
  Exit --> Reconcile[Post-launch reconciliation]
  Reconcile --> Report[Immutable sanitized final report]
```

Final decisions are bounded: `ROLLED_BACK`, `PARTIALLY_DEPLOYED`, `HYPERCARE_REQUIRED`, `COMPLETED_WITH_LIMITATIONS`, or `CONTROLLED_ROLLOUT_COMPLETED`. There is no unconditional production success state.

## Deferred production-only checks

Real production preflight, deployment, canary, rollback, DNS/TLS mutation, provider certification against live panels, real payment enablement, customer migration and real completion reporting require protected operator action and production evidence outside Codex.
