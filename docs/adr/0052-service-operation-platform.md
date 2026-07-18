# ADR 0052: Service-operation platform

## Status
Accepted for Milestone 6-C1.

## Decision
Post-provisioning changes are represented as immutable service operations with versioned policy snapshots, desired-change records, attachment plans, provider-operation references, state revisions, approvals, reconciliation and compensation records.

Billable operations are commercial-origin records linked to new quotes, orders, invoices and payments. Non-commercial operations still require eligibility, authorization, reason codes, idempotency, cooldown and verification. Reductions are high-risk, policy disabled by default for customer self-service and require separate approval. Provider counter reset is distinct from lifetime usage accounting. Suspension preserves remote identity, credentials, traffic, expiry, limits and financial history. Credential rotation uses pending encrypted material, provider verification, delivery revision refresh and stable subscription URL preservation.

## Consequences
Service-operation routes cannot directly mark billable work paid and cannot perform raw adapter calls. Partial or uncertain attachment results remain visible and force reconciliation/manual review rather than false success. Compensation is a separate durable operation and never rewrites the original operation or financial history.
