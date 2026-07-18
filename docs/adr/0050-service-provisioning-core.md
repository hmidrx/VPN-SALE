# ADR 0050: Milestone 6-B1 Service Provisioning Core

## Status
Accepted

## Context
Milestones 6-A1, 6-A2A and 6-A2B certified provider inventory, write gating, credential vaulting, mutation plans, operation execution and postcondition verification. Commerce now needs a service domain that consumes paid-order fulfillment without bypassing provider safety controls.

## Decision
- Model services, entitlements, lifecycle, attachments, fulfillment requests, allocation policy versions, pools, targets, reservations, workflows and reconciliation issues as first-class records.
- Keep immutable commercial entitlement snapshots on services and never reload mutable catalog terms during provisioning.
- Maintain the commerce-to-fulfillment boundary through durable `READY_FOR_FULFILLMENT` ingestion and unique `(order_item_id, unit_index)` keys.
- Publish immutable allocation policy versions. Existing services retain the selected policy snapshot.
- Reserve capacity transactionally using local hard limits, active allocations, pending reservations and safety reserves. Missing provider counters never imply unlimited capacity.
- Support multi-inbound services through one service with many attachments. Use shared remote identity only when the certified contract supports it; otherwise use per-attachment identity and credential references.
- Create provider operations through the 6-A2B operation engine only. Service and API layers never import panel adapters or execute raw transports.
- Represent partial provisioning honestly through `PROVISIONING_FAILED`, `MANUAL_REVIEW`, reconciliation issues and repair/compensation plans.
- Add safe ownership evidence using service/attachment mappings, provider-operation IDs, bounded technical labels, remote references and credential fingerprints; remarks are not authorization evidence.

## Consequences
Customer and reseller APIs can show safe service status, but cannot expose configuration, provider infrastructure, credentials, QR codes or subscription links until Milestone 6-B2. Operators receive policy, allocation, capacity, provisioning and reconciliation controls without arbitrary provider mutation forms.
