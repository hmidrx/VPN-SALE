# Milestone 5-F Plan — Knowledge, Education and Status Platform

## Scope
Milestone 5-F adds a production-grade, safe knowledge-base and public status platform. It includes versioned articles/tutorials, structured blocks, educational media validation, FAQ, troubleshooting, Persian-ready search, contextual guide recommendations, feedback, status components, incidents, maintenance and notification boundaries across backend, customer web, Telegram Mini App, reseller web, Telegram bot and admin web.

## Non-goals
No VPN panel adapters, server/node/inbound models, provisioning, subscription delivery, real payment gateways, fabricated service health, fabricated uptime, unverified third-party download URLs, arbitrary HTML/JavaScript/CSS/SQL/scripts/plugins, arbitrary AI answers or executable content are implemented.

## Architecture
```mermaid
flowchart LR
  Admin[Admin console] --> Draft[Typed draft/version]
  Draft --> Validate[Domain validation]
  Validate --> Preview[Scoped preview]
  Preview --> Publish[Atomic publish]
  Publish --> Outbox[Outbox invalidation]
  Outbox --> Cache[Redis versioned cache]
  Cache --> Public[Customer/Reseller/Mini App/Bot]
```

## Article lifecycle
```mermaid
stateDiagram-v2
  DRAFT --> VALIDATION_FAILED
  VALIDATION_FAILED --> DRAFT
  DRAFT --> READY_FOR_REVIEW
  READY_FOR_REVIEW --> APPROVED
  APPROVED --> SCHEDULED
  APPROVED --> PUBLISHING
  SCHEDULED --> PUBLISHING
  PUBLISHING --> PUBLISHED
  PUBLISHING --> PUBLISH_FAILED
  PUBLISHED --> SUPERSEDED
  PUBLISHED --> ROLLED_BACK
  SUPERSEDED --> ARCHIVED
  ROLLED_BACK --> ARCHIVED
```

## Media processing
```mermaid
flowchart TD
  Upload --> Inspect[MIME/content inspection]
  Inspect -->|safe| Process[variants/poster metadata]
  Inspect -->|mismatch| Reject[REJECTED]
  Inspect -->|executable/html/bomb| Quarantine[QUARANTINED]
  Process --> Ready[READY opaque ref]
```

## Search
```mermaid
flowchart LR
  Query --> Normalize[Persian normalization]
  Normalize --> RateLimit[rate limit]
  RateLimit --> Index[Published search document]
  Index --> Filter[Audience/tenant filters]
  Filter --> Results[Safe snippets]
```

## Guide recommendation
```mermaid
flowchart TD
  Context[Safe context] --> Candidates[Published authorized articles]
  Candidates --> Score[Deterministic priority score]
  Score --> Result[Recommended/alternatives/missing-guide]
```

## Troubleshooting flow
```mermaid
flowchart TD
  Start --> Question
  Question --> Choice
  Choice --> Instruction
  Instruction --> EndSuccess
  Choice --> Escalate[Support escalation safe summary]
```

## Support escalation
```mermaid
flowchart LR
  Article --> Context[Safe article/version refs]
  Flow --> Context
  Context --> Support[Milestone 5-E ticket draft]
  Support --> AgentReview[Agent manually sends suggestion]
```

## Cache invalidation
```mermaid
flowchart LR
  Publish --> Transaction
  Transaction --> Outbox
  Outbox --> Worker
  Worker --> RedisDelete[Delete versioned keys]
  RedisDelete --> DBFallback[Safe DB fallback]
```

## Incident lifecycle
```mermaid
stateDiagram-v2
  DRAFT --> INVESTIGATING
  INVESTIGATING --> IDENTIFIED
  IDENTIFIED --> MONITORING
  MONITORING --> RESOLVED
```

## Maintenance
```mermaid
stateDiagram-v2
  ANNOUNCED --> IN_PROGRESS
  IN_PROGRESS --> COMPLETED
  ANNOUNCED --> CANCELLED
```

## Status notifications
```mermaid
flowchart LR
  IncidentUpdate --> OutboxEvent
  MaintenanceEvent --> OutboxEvent
  OutboxEvent --> Idempotency
  Idempotency --> Customer
  Idempotency --> Reseller
  Idempotency --> Telegram
```

## Validation
Required checks remain `docker compose config`, `ruff format --check .`, `ruff check .`, `pyright`, `pytest`, `npm run lint`, `npm run typecheck`, `npm run test` plus focused knowledge/status/bot tests and migration verification.
