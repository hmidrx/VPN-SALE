# Milestone 4-A1 Plan: Provider-Neutral Payment Core Backend

## Scope
Milestone 4-A1 adds a backend-only payment foundation. It deliberately excludes payment UI, real gateways, merchant credentials, card/bank data, cryptocurrency, VPN provisioning, subscriptions and analytics.

## Implemented foundation
- Provider-neutral payment tables for methods, localizations, policies, intents, attempts, verifications, settlements, webhook inbox items, refunds, refund attempts, idempotency records and reconciliation runs.
- Explicit provider code plus adapter version on every payment method and webhook correlation path.
- Deterministic fake adapter for tests and development only; the registry rejects fake registration in production.
- Domain state machines for intents and attempts with terminal-state protection.
- Normalized adapter contracts for create, return parsing, verification, query, webhook verification/parsing, refund creation/query and health.
- Customer-safe method listing and payment intent stubs for wallet top-up and external order payment.
- Admin-safe payment method inspection/creation, dry-run reconciliation endpoint and bounded webhook ingestion endpoint.

## Diagrams

### Intent creation
```mermaid
sequenceDiagram
  Customer->>API: Create wallet top-up or order-payment intent
  API->>Payment Domain: Validate purpose, amount and method policy
  Payment Domain->>DB: Persist immutable intent and first attempt
  API->>Adapter Registry: Select provider_code + adapter_version
  Adapter Registry->>Fake/Registered Adapter: create_payment
  Adapter-->>API: Normalized redirect action
  API-->>Customer: intent_reference + safe action
```

### Redirect flow
```mermaid
flowchart TD
  A[Intent attempt] --> B[Adapter create_payment]
  B --> C[Customer redirect action]
  C --> D[Provider hosted page]
  D --> E[Provider-neutral return endpoint]
```

### Return and verification
```mermaid
sequenceDiagram
  Browser->>API: Return parameters
  API->>Adapter: parse_return only
  API->>Payment App: mark returned / requires verification
  Payment App->>Adapter: verify_payment server-side
  Adapter-->>Payment App: Normalized result
  Payment App->>Settlement: settle only after exact match
```

### Webhook ingestion
```mermaid
flowchart TD
  W[Raw webhook] --> L{Body size <= limit}
  L -->|no| R[Reject 413]
  L -->|yes| V[Adapter signature verification]
  V --> I[Inbox row with digest and allowlisted headers]
  I --> P[Idempotent processing]
```

### Duplicate webhook
```mermaid
flowchart LR
  A[Webhook event] --> B[provider event reference + digest]
  B --> C{Unique constraint exists?}
  C -->|yes| D[Replay detected; no mutation]
  C -->|no| E[Process safely]
```

### Wallet top-up settlement
```mermaid
flowchart TD
  V[Verified success] --> M[Exact amount and IRR check]
  M --> J[Balanced journal]
  J --> C[Credit wallet CASH bucket]
  C --> S[Payment settlement recorded exactly once]
```

### External invoice settlement
```mermaid
flowchart TD
  V[Verified success] --> I[Load immutable unpaid invoice amount]
  I --> J[Balanced external-payment clearing journal]
  J --> P[Mark invoice/order paid]
  P --> F[READY_FOR_FULFILLMENT outbox once]
```

### Refund
```mermaid
flowchart TD
  A[Authorized admin request] --> B[Original settlement]
  B --> C{Refund total <= refundable?}
  C -->|no| D[Reject]
  C -->|yes| E[Adapter refund]
  E --> F[Compensating journal]
  F --> G[Refund succeeded]
```

### Expiration and late settlement
```mermaid
flowchart TD
  A[Bounded expiry command] --> B[Expire non-terminal intents]
  C[Provider later verifies success] --> D[Do not settle automatically]
  D --> E[RECONCILIATION_REQUIRED]
```

### Reconciliation
```mermaid
flowchart TD
  R[Dry-run reconciliation] --> A[Intent/attempt checks]
  R --> B[Settlement/ledger checks]
  R --> C[Wallet/order/outbox checks]
  R --> D[Refund and webhook checks]
  D --> E[Typed mismatch codes]
```

### Adapter-version selection
```mermaid
flowchart LR
  M[Payment method] --> K[provider_code + adapter_version]
  K --> R[Registry]
  R -->|known| A[Adapter]
  R -->|unknown| F[Fail closed]
```

## Security and rollback notes
- Gateway credentials are represented only by secret references and credential state/version; no credential retrieval API is introduced.
- Raw webhook bodies and signatures are not returned by APIs.
- Migration downgrade drops only Milestone 4-A1 payment tables and payment permissions; it seeds no production payment data.
- Real provider integration remains a future decision pending exact API specs and test credentials.
