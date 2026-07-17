# Milestone 5-C — Reseller Core and Administrator Controls

Milestone 5-C adds the production-grade reseller domain, administrator management console foundations, reseller-facing backend API foundations, migrations, tests and documentation. It deliberately excludes the full reseller-web portal, VPN provisioning, panel adapters, provider data, live support, referrals, coupons and payment gateways.

## Scope

- Reseller accounts use opaque references, linked independent customer principals, stable tiers, lifecycle status, settlement mode, price-book references, financial-account references, credit terms, quota overrides, remark policy, timestamps and optimistic versions.
- Lifecycle commands are legal transitions only: draft, review, active, suspended, blocked, terminated and archived. There is no arbitrary status setter.
- Tiers use stable internal codes: `STARTER`, `STANDARD`, `PROFESSIONAL`, `ENTERPRISE`. Account-specific overrides are stricter than tier defaults.
- Wholesale pricing is backend-authoritative and integer-rial only. Quotes/orders must snapshot the evaluated wholesale price, discounts, floors, optional retail metadata and explanation.
- Financial accounts support prepaid wallet funding and controlled credit. Credit is a ledger-backed receivable concept with explicit limits; it is not an unrestricted negative wallet.
- Managed customers are tenant-isolated and never grant impersonation. Transfers and releases require versioned workflows and approval where high risk.
- Reseller-funded orders distinguish beneficiary customer from paying reseller and emit one normalized fulfillment outbox request without creating VPN services.
- Remark templates are presentation labels only. They cannot alter UUIDs, credentials, Host, SNI, Address, Path, protocol, transport or security settings.

## Lifecycle

```mermaid
stateDiagram-v2
  DRAFT --> PENDING_REVIEW
  DRAFT --> ARCHIVED
  PENDING_REVIEW --> ACTIVE
  PENDING_REVIEW --> DRAFT
  PENDING_REVIEW --> BLOCKED
  ACTIVE --> SUSPENDED
  ACTIVE --> BLOCKED
  ACTIVE --> TERMINATED
  SUSPENDED --> ACTIVE
  SUSPENDED --> BLOCKED
  SUSPENDED --> TERMINATED
  BLOCKED --> SUSPENDED
  BLOCKED --> TERMINATED
  TERMINATED --> ARCHIVED
```

## Pricing precedence

```mermaid
flowchart TD
  A[Immutable product-version base price] --> B[Reseller exact override]
  B --> C[Price-book product rule]
  C --> D[Category rule]
  D --> E[Tier rule]
  E --> F[Volume tier]
  F --> G[Reseller-allowed promotion]
  G --> H[Minimum price and margin floors]
  H --> I[Immutable pricing snapshot]
```

## Managed customer ownership

```mermaid
stateDiagram-v2
  INVITED --> MANAGED
  MANAGED --> TRANSFER_PENDING
  TRANSFER_PENDING --> MANAGED
  MANAGED --> RELEASE_PENDING
  RELEASE_PENDING --> RELEASED
  MANAGED --> REVOKED
  INVITED --> REVOKED
```

## Prepaid checkout

```mermaid
sequenceDiagram
  participant R as Reseller
  participant API as Backend API
  participant W as Wallet/Ledger
  participant O as Orders
  R->>API: Create quote/order for managed customer
  API->>API: Validate active reseller, ownership, eligibility, quotas
  API->>W: Reserve reseller wallet funds
  API->>O: Create order and invoice snapshots
  API->>W: Capture one ledger-backed debit
  API->>O: Mark READY_FOR_FULFILLMENT and emit outbox
```

## Credit reservation

```mermaid
flowchart LR
  A[Approved credit facility] --> B{Blocked or overdue?}
  B -- yes --> C[Reject new use]
  B -- no --> D[Lock facility row]
  D --> E{Utilized + reservation <= limit?}
  E -- no --> F[Reject and Security Center event]
  E -- yes --> G[Ledger-backed receivable reservation]
```

## Reseller-funded order

```mermaid
flowchart TD
  A[Reseller token] --> B[ACTIVE reseller]
  B --> C[Managed customer belongs to reseller]
  C --> D[Eligible available product]
  D --> E[Evaluate reseller price book]
  E --> F[Validate quotas and risk limits]
  F --> G[Quote with immutable pricing and remark snapshot]
  G --> H[Order with payer reseller and beneficiary customer]
  H --> I[Prepaid or controlled-credit financial effect]
  I --> J[READY_FOR_FULFILLMENT outbox, no VPN service]
```

## Remark resolution

```mermaid
flowchart TD
  A[Admin policy prefix/suffix] --> B[Product override]
  B --> C[Reseller default template]
  C --> D[Customer label]
  D --> E[Order requested remark]
  E --> F[Placeholder registry validation]
  F --> G[Length and unsafe-content checks]
  G --> H[Escaped immutable presentation snapshot]
```

## Approval workflow

```mermaid
sequenceDiagram
  participant C as Creator Admin
  participant A as Approver Admin
  participant SC as Security Center
  C->>SC: Request high-risk financial/ownership action
  SC-->>C: Pending approval reference
  A->>SC: Approve with separate principal
  SC-->>A: Deny if same creator
  SC->>SC: Audit decision and apply command idempotently
```

## Rollback

The Alembic downgrade drops only reseller-owned tables and seeded reseller permissions. It does not rewrite historical catalog, order, wallet, payment or customer migrations.
