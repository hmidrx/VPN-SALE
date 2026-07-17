# Milestone 4-A2B2 Plan — Payment recovery operations

## Scope
Milestone 4-A2B2 completes the recovery layer around the provider-neutral payment core: refunds, two-person approvals, compensating journals, reconciliation, safe repairs, late settlements, unapplied payments and webhook dead-letter recovery. It keeps the existing fake-adapter-only boundary: no real gateway, card-to-card, provider provisioning, reseller or support integration is introduced.

## Financial invariants
- Rial integers with explicit `IRR` currency remain authoritative.
- Original intents, attempts, settlements, journals and webhook evidence are immutable.
- Refunds are new compensating effects and never rewrite the original settlement.
- Trusted server-side provider verification is required before a refund can be successful.
- Administrators can request, approve, retry, reconcile and execute safe repair plans, but cannot mark payments/refunds successful, credit wallets directly or mark invoices paid.
- Invalid-signature webhooks are permanently untrusted.

## Permissions
New permission codes are seeded idempotently: `payment_refunds.read`, `payment_refunds.manage`, `payment_refunds.approve`, `payments.reconcile`, `payments.repair`, `payments.late_settlement.manage`, `payments.unapplied.read`, `payments.unapplied.manage` and `payment_webhooks.recover`.

## Refund eligibility
```mermaid
flowchart TD
  S[Immutable settlement] --> T{Trusted verified success?}
  T -- no --> Block[Reject: settlement not trusted]
  T -- yes --> C{Provider supports refund?}
  C -- no --> Block2[Reject: unsupported]
  C -- yes --> P{Purpose}
  P -- Order --> O{Commerce state refundable?}
  P -- Wallet top-up --> W{Unreserved CASH coverage?}
  O -- yes --> Full[Full refund eligible]
  W -- yes --> Full
  O -- no --> Review[Not refundable]
  W -- no --> Unsafe[Unsafe wallet refund denied]
```

## Refund approval
```mermaid
flowchart TD
  R[Refund request] --> Risk{High risk?}
  Risk -- no --> A[Approved for execution]
  Risk -- yes --> P[Pending approval]
  P --> Sep{Approver differs from creator?}
  Sep -- no --> Deny[Self-approval denied]
  Sep -- yes --> Exp{Approval fresh and same version?}
  Exp -- no --> Restart[Require new approval]
  Exp -- yes --> A
```

## Provider refund verification
```mermaid
sequenceDiagram
  participant API
  participant DB
  participant Fake as Versioned fake adapter
  API->>DB: Commit request and attempt
  API->>Fake: create_refund outside transaction
  Fake-->>API: normalized provider result
  API->>Fake: query_refund/verify trusted state
  API->>DB: Persist provider result idempotently
```

## Compensating ledger
```mermaid
flowchart LR
  Original[Original settlement journal] --> Immutable[Unchanged]
  Refund[Verified refund success] --> Journal[New balanced compensation journal]
  Journal --> Effect[Order/invoice/wallet effect through application service]
  Journal --> Audit[Audit + timeline + outbox]
```

## Reconciliation and safe repair
```mermaid
flowchart TD
  Run[Typed reconciliation run] --> M[Mismatches with stable codes]
  M --> E[Immutable evidence]
  M --> R{Repair classification}
  R -- Safe derived state --> Plan[Backend-generated dry-run plan]
  Plan --> Approve[Approved execution with version/idempotency]
  R -- Manual/critical --> Review[Manual review or escalation]
```

## Critical blocked repair
```mermaid
flowchart TD
  C[Critical mismatch] --> Examples[Duplicate settlement, unbalanced journal, amount mismatch, invalid signature effect]
  Examples --> Block[No automatic repair]
  Block --> Security[Security Center event]
  Block --> Audit[Audit trail]
```

## Late settlement
```mermaid
flowchart TD
  Provider[Trusted late provider success] --> State{Commercial state still compatible?}
  State -- Wallet safe --> Credit[Apply late wallet top-up through wallet service]
  State -- Order payable --> Pay[Apply late order payment without duplicate fulfillment]
  State -- Cancelled/incompatible --> Case[Late-settlement case]
  Case --> Unapplied[Unapplied liability or refund-required]
```

## Unapplied payment
```mermaid
flowchart TD
  Money[Verified external money] --> Inapplicable{Can apply safely?}
  Inapplicable -- no --> Liability[Unapplied payment liability]
  Liability --> Review[Reviewed application or refund]
  Review --> Resolution[Resolution reference, audit and immutable evidence]
```

## Dead-letter recovery
```mermaid
flowchart TD
  Webhook[Webhook inbox] --> Valid{Valid signature?}
  Valid -- no --> Untrusted[Permanent untrusted state]
  Valid -- yes --> Retry{Retryable/dead-letter?}
  Retry -- retryable --> Reopen[Bounded idempotent retry]
  Retry -- needs query --> Query[Provider query via fake adapter when supported]
  Reopen --> Audit[Audit + Security Center on critical failures]
```

## Administrator UI
Admin-web extends payment operations with Persian RTL pages for refund management, reconciliation/safe repair, late settlements, unapplied payments and webhook recovery. The UI uses real backend API client methods, shows rial plus derived toman where relevant, uses LTR technical references, avoids browser persistence for financial state and never exposes credentials or raw webhook payloads.

## Tests and operations
Deterministic coverage is added at the domain/API/UI boundaries for refund eligibility, wallet-top-up safety, two-person approval, provider verification, mismatch repair boundaries, late/unapplied states and webhook recovery denial for invalid signatures. Migration downgrade removes only this milestone’s recovery tables/columns and permissions.
