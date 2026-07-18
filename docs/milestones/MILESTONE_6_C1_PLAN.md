# Milestone 6-C1 — Service-operation platform

Date: 2026-07-18.

Milestone 6-C1 introduces a durable post-provisioning operation model for ACTIVE and otherwise eligible services. It reuses the 6-A2B provider mutation engine, 6-B1 immutable service entitlements and 6-B2 delivery/subscription platform. Service migration, failover, allocation replacement and arbitrary provider commands remain out of scope.

## Lifecycle

Service operations are separate from commercial orders. Draft/quoted/payment/approval/execution/verification/reconciliation states are explicit, optimistic-versioned and immutable-history preserving. Billable operations start in `AWAITING_PAYMENT`; non-billable safe operations can queue directly; high-risk reductions require `PENDING_APPROVAL` and deny requester self-approval.

## Commercial operations

Renewal, traffic add-on, duration extension and limit increases use backend policy pricing in integer rial. A paid checkout links a new quote, order, invoice and payment to one service operation. Provider failures never rewrite payment history or trigger automatic refunds.

## Technical operations

Suspend/resume, reset traffic, clear IP/HWID, credential rotation, subscription token revocation/rotation and Delivery Profile refresh are policy-gated operations. Traffic reset records a reset generation and never erases lifetime usage. Credential rotation promotes new encrypted material only after remote verification and refreshes delivery without changing stable subscription URLs.

## Multi-attachment execution

Each remote mutation creates one attachment plan per attachment. `ALL_REQUIRED` is the default success policy; any uncertainty on required attachments prevents service-level success and moves the operation to `UNCERTAIN`, `PARTIALLY_APPLIED`, reconciliation or manual review.

## Provider and reconciliation rules

Service-operation code stores provider-operation references and sanitized digests only. It must not call adapters or raw provider HTTP. Execution reads before write, uses 6-A2B write gates, verifies read-after-write postconditions and reconciles ambiguous outcomes before retry.

## UI/API surfaces

Customer, reseller and admin APIs expose eligibility, operation creation/history and approval primitives. Interfaces must show only backend-evaluated operations, no panel/node/inbound IDs, no credentials/tokens/configurations and no arbitrary provider-command forms.
