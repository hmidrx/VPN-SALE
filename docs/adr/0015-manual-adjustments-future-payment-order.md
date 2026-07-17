# ADR 0015: Manual adjustments and future payment/order integration

## Status
Accepted for Milestone 3-A1.

## Decision
Manual credit/debit is reserved for administrators with `wallets.adjust` and always posts balanced ledger entries with bounded reason text and stable reason code. Reversal creates a new opposite entry and never mutates the original. Future checkout will follow: quote, order creation, wallet reservation, payment or wallet capture, invoice, provisioning request, allocation, provider adapter. Payment modules must later post through ledger ports instead of updating balances directly.

## Open decision
High-risk deductions remain immediately posted by narrowly privileged operators in this milestone. A two-person approval workflow is deferred.
