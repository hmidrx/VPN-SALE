# Milestone 5-B Plan — Customer Administration Platform

## Scope
Milestone 5-B adds a production-grade administrator surface for existing customer, session, wallet, ledger, order/payment history, audit and Security Center data. It intentionally excludes reseller, support chat/knowledge base, VPN provider, provisioning, subscription delivery, coupon, referral, marketing and customer impersonation work.

## Architecture
```mermaid
flowchart LR
  Admin[Admin Web RTL] --> API[FastAPI admin customer APIs]
  API --> App[Application commands]
  App --> Identity[Identity + customer sessions]
  App --> Wallet[Wallet projection]
  App --> Ledger[Double-entry ledger]
  App --> Audit[Audit logs]
  App --> Sec[Security Center]
  App --> Jobs[Export/Bulk job tables]
```

## Customer 360
```mermaid
flowchart TD
  Profile[Customer 360] --> Overview
  Profile --> Identity
  Profile --> Security[Sessions and events]
  Profile --> Wallet[Balances, buckets, reservations]
  Wallet --> LedgerLinks[Ledger links]
  Profile --> Commerce[Orders invoices payments refunds]
  Profile --> NotesTags[Internal notes and tags]
  Profile --> Activity[Audit/security timeline]
```

## Lifecycle
```mermaid
stateDiagram-v2
  PENDING --> ACTIVE: activate
  PENDING --> DEACTIVATED: deactivate
  ACTIVE --> SUSPENDED: suspend
  ACTIVE --> BLOCKED: block
  ACTIVE --> DEACTIVATED: deactivate
  SUSPENDED --> ACTIVE: restore
  SUSPENDED --> BLOCKED: block
  SUSPENDED --> DEACTIVATED: deactivate
  BLOCKED --> [*]
  DEACTIVATED --> [*]
```
All lifecycle commands require permission, reason code, idempotency header where applicable, expected version, audit and session revocation on restrictive transitions.

## Session revocation
```mermaid
sequenceDiagram
  Admin->>API: revoke one/all with reason
  API->>RBAC: customers.manage_security
  API->>DB: mark session revoked_at
  API->>Audit: customer.session_revoked
  API-->>Admin: authoritative result
```

## Wallet freeze and adjustments
```mermaid
flowchart TD
  Freeze[Freeze/unfreeze] --> WalletStatus[Wallet.status]
  WalletStatus --> Policy[spending/top-up/refund/reservation/webhook/reconciliation policy documented]
  Request[Adjustment request] --> Risk{High risk?}
  Risk -- No --> Journal[Balanced journal]
  Risk -- Yes --> Approval[Separate approver]
  Approval --> Self{Creator?}
  Self -- yes --> Deny[Security event]
  Self -- no --> Journal
  Journal --> Projection[Projection/bucket update]
  Journal --> Audit
  Reversal[Reversal] --> Compensating[Compensating journal]
```

## Exports
```mermaid
sequenceDiagram
  Admin->>API: create export allowlisted fields
  API->>DB: bounded query
  API->>CSV: formula-safe content
  API->>DB: opaque short-lived reference
  Admin->>API: download with current auth
  API->>Audit: request/download
```

## Bulk execution and retry
```mermaid
flowchart TD
  Select[Explicit refs or saved bounded filter] --> Snapshot[Freeze target snapshot]
  Snapshot --> DryRun[Dry preview]
  DryRun --> Confirm[Reason and confirmation]
  Confirm --> Queue[Queued job]
  Queue --> Items[Per-customer ordinary commands]
  Items --> Results[Per-item result]
  Results --> Retry[Retry failed only with item idempotency]
```

## Permissions
Milestone 5-B adds `customers.*` and `customer_wallets.*` permissions. Super Admin receives them via idempotent migration seeding. Read, lifecycle, security, notes, tags, bulk, export, wallet-freeze, adjustment, cash-adjustment and approval rights remain separate.

## Security, privacy and masking
Raw tokens, CSRF, Telegram initData, token hashes and credentials are never returned. Telegram IDs are masked in directory rows and only exposed in detail paths for authorized administrators. Notes are internal only. Exports use allowlisted fields, short-lived opaque references and CSV injection protection.

## Rollback
Downgrade drops only Milestone 5-B customer-admin tables and seeded permissions. It does not delete or mutate customers, sessions, wallets, ledger entries, invoices, payments, settlements or refunds.
