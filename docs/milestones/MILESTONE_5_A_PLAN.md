# Milestone 5-A Configuration and Branding Platform

Milestone 5-A introduces a production-grade runtime configuration platform for branding, themes, localized templates, feature flags, safe navigation, Telegram menus, media assets, previews, publishing, scheduling, rollback, caching and audit.

## Scope

Included: typed backend configuration domains, immutable releases, admin configuration center, runtime APIs, customer/Mini App consumption, safe Telegram menus/templates, media asset governance, permissions, migrations, tests and documentation.

Excluded: customer-management operations, resellers, support/live chat, knowledge base, VPN panels, provisioning, subscriptions, real gateways, coupons, referrals and analytics.

## Configuration precedence

```mermaid
flowchart TD
  A[Compiled safe defaults] --> B[Immutable environment boundaries]
  B --> C[Active database release]
  C --> D[Channel overrides]
  D --> E[Locale content]
  E --> F[Authorized short-lived preview]
```

## Draft, validation and publish lifecycle

```mermaid
stateDiagram-v2
  [*] --> DRAFT
  DRAFT --> VALIDATION_FAILED
  DRAFT --> READY_FOR_REVIEW
  VALIDATION_FAILED --> DRAFT
  READY_FOR_REVIEW --> APPROVED
  APPROVED --> SCHEDULED
  APPROVED --> PUBLISHING
  SCHEDULED --> PUBLISHING
  PUBLISHING --> PUBLISHED
  PUBLISHING --> PUBLISH_FAILED
  PUBLISHED --> SUPERSEDED
  PUBLISHED --> ROLLED_BACK
  SCHEDULED --> CANCELLED
  DRAFT --> ARCHIVED
```

## Atomic release

```mermaid
sequenceDiagram
  participant Admin
  participant API
  participant DB
  participant Outbox
  participant Redis
  Admin->>API: publish approved draft
  API->>DB: validate and lock release scope
  DB->>DB: supersede old, insert release, insert snapshot
  DB->>Outbox: cache invalidation event
  DB-->>API: commit
  API->>Redis: refresh best-effort cache
```

## Preview

```mermaid
sequenceDiagram
  Admin->>API: create scoped preview
  API->>DB: verify permission and draft
  API-->>Admin: opaque short-lived reference
  Admin->>Runtime: request preview with reference
  Runtime->>DB: verify active admin scope
  Runtime-->>Admin: labeled preview snapshot
```

## Schedule and rollback

```mermaid
flowchart LR
  A[Approved release] --> B[UTC scheduled time]
  B --> C[Scheduler validates idempotency]
  C --> D[Atomic publish]
  D --> E[Rollback request]
  E --> F[Clone historical immutable snapshot]
  F --> G[New effective release]
```

## Runtime delivery and cache invalidation

```mermaid
flowchart TD
  R[Runtime API] --> S[Runtime snapshot]
  S --> E[ETag response]
  S --> W[Customer web SSR]
  S --> M[Mini App]
  S --> T[Telegram bot cache]
  P[Publish transaction] --> O[Transactional outbox]
  O --> C[Versioned invalidation]
  C --> R
  C --> T
```

## Feature evaluation

```mermaid
flowchart TD
  A[Flag safe default] --> B[Environment boundary]
  B --> C[Dependencies]
  C --> D[Channel/auth/role/locale]
  D --> E[Schedule window]
  E --> F[Deterministic keyed rollout]
  F --> G[Evaluated boolean only]
```

## Telegram menu rendering

```mermaid
flowchart LR
  A[Published Telegram menu] --> B[Validate action registry]
  B --> C[Generate opaque cfg callback]
  C --> D[Bot cache]
  D --> E[Reply/inline keyboard]
  B -->|invalid| F[Compiled safe menu]
```

## Media processing

```mermaid
flowchart TD
  U[Upload] --> M[MIME/content sniff]
  M --> D[Decode dimensions]
  D --> B[Decompression bomb guard]
  B --> S[Strip metadata]
  S --> R[READY]
  M --> Q[REJECTED/QUARANTINED]
  B --> Q
  R --> P[Publish reference allowed]
```

## Validation and security

Publication blocks executable templates, unknown placeholders, raw CSS/JS/HTML, unsafe URLs, unregistered actions, callback injection, low-contrast themes, invalid feature dependencies, secret-like public values and non-ready assets.
