# ADR 0028: Financial Adjustments, Approvals, Exports, and Bulk Operations

## Status
Accepted

Customer financial adjustments are requests that post balanced double-entry journals only after risk evaluation. High-risk or cash-bucket requests require a separate approver and deny self-approval with a Security Center event. Original ledger records stay immutable; reversals are compensating journals. Exports are asynchronous job records with allowlisted fields and short-lived opaque references. Bulk operations are bounded, idempotent jobs with per-item outcomes and safe retry.
