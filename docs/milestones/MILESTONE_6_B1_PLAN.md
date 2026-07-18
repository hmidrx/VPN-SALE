# Milestone 6-B1 Plan — Service Provisioning Core

## Scope

Milestone 6-B1 connects paid commerce to the certified provider-write layer without delivering customer configuration material. It introduces durable service records, immutable entitlement snapshots, fulfillment request ingestion, allocation policy versions, pools, targets, capacity reservations, multi-inbound attachments, provisioning workflow references, reconciliation issues, repair/compensation planning placeholders, permissions and operator surfaces.

## Invariants

- Only `READY_FOR_FULFILLMENT` orders with paid financial state and captured payment may create a service.
- The `(order_item_id, unit_index)` pair is unique across fulfillment requests and services.
- Service `ACTIVE` requires every required attachment to be verified by Milestone 6-A2B postconditions.
- Allocation policy versions are immutable once published; services retain a snapshot.
- Capacity is local and conservative: hard maximum minus active attachments, pending reservations and reserves.
- Provider mutations are represented only by provider-operation references; service code does not call panel adapters.
- Customer/reseller status APIs must not expose provider kind, panel, node, inbound, credentials, subscription links or configuration.

## Paid order to service

```mermaid
sequenceDiagram
  participant Checkout
  participant Outbox
  participant Fulfillment
  participant Service
  participant Allocation
  participant ProviderOps
  Checkout->>Outbox: READY_FOR_FULFILLMENT after commit
  Outbox->>Fulfillment: deliver event with dedupe key
  Fulfillment->>Service: create PENDING_ALLOCATION service
  Service->>Allocation: resolve published policy
  Allocation->>Allocation: reserve capacity transactionally
  Allocation->>ProviderOps: create A2B provider operations
  ProviderOps->>Service: verified postconditions per attachment
  Service->>Fulfillment: ACTIVE and result complete
```

## Allocation selection

```mermaid
flowchart TD
  A[Entitlement snapshot] --> B[Published policy version]
  B --> C[Build sanitized candidates]
  C --> D{Fresh inventory and health?}
  D -- no --> R[Reject with safe reason]
  D -- yes --> E{Write certification enabled?}
  E -- no --> R
  E -- yes --> F{Capacity available after reserves?}
  F -- no --> R
  F -- yes --> G[Stable weighted ordering]
  G --> H[Freeze selected target snapshot]
```

## Capacity reservation

```mermaid
flowchart LR
  A[Target hard max] --> B[Subtract active allocations]
  B --> C[Subtract pending reservations]
  C --> D[Subtract safety reserve]
  D --> E{Available > 0?}
  E -- yes --> F[Insert unique ACTIVE reservation]
  E -- no --> G[Capacity exhausted]
```

## Multi-inbound provisioning

```mermaid
sequenceDiagram
  participant Workflow
  participant AttachmentA
  participant AttachmentB
  participant A2B
  Workflow->>AttachmentA: prepare identity and operation
  Workflow->>AttachmentB: prepare identity and operation
  AttachmentA->>A2B: execute operation
  AttachmentB->>A2B: execute operation
  A2B-->>AttachmentA: verified
  A2B-->>AttachmentB: verified or failed/uncertain
  Workflow->>Workflow: activate only if required set verified
```

## Provider-operation orchestration

Service provisioning creates provider-operation plans and records their IDs on attachments. The operation executor, write gates, canary certificates, contract/version checks and postcondition verification remain owned by Milestone 6-A2B.

```mermaid
flowchart TD
  A[Attachment desired state] --> B[Credential vault reference]
  B --> C[Mutation preflight]
  C --> D[Immutable mutation plan digest]
  D --> E[A2B executor]
  E --> F[Read-after-write]
  F --> G[Attachment verified state]
```

## Partial failure, reconciliation and compensation

```mermaid
flowchart TD
  A[Provisioning attempt] --> B{All required verified?}
  B -- yes --> C[ACTIVE]
  B -- no --> D{Commit state certain?}
  D -- no --> E[MANUAL_REVIEW]
  D -- yes --> F[Repair plan or compensation plan]
  F --> G[Operator approval if destructive]
```

```mermaid
flowchart TD
  A[Service desired state] --> B[Attachment allocation snapshot]
  B --> C[Provider operation result]
  C --> D[Authoritative remote read]
  D --> E{Matched?}
  E -- yes --> F[MATCHED]
  E -- no --> G[Reconciliation issue]
  G --> H[Repair/compensation/manual review]
```

## Order fulfillment projection

```mermaid
sequenceDiagram
  participant Service
  participant Fulfillment
  participant OrderProjection
  Service->>Fulfillment: all required attachments verified
  Fulfillment->>OrderProjection: mark complete idempotently
  Service-->>Fulfillment: duplicate retry returns existing result
```

## Operator runbook

1. Publish allocation policy versions only after validation confirms every referenced pool target exists and is certified.
2. Monitor fulfillment, provisioning and reconciliation queues using bounded cursor filters.
3. Retry only workflows marked retry-eligible; uncertain provider operations must reconcile before another create.
4. Approve destructive compensation only after ownership evidence is verified.
5. Treat provider version or contract drift as recertification-required for new provisioning.

## Limitations before 6-B2

No delivery profiles, URI generation, QR codes, subscription links, customer configuration display, renewals, add-ons, migrations between targets or full suspend/resume/terminate operations are implemented in this milestone.
