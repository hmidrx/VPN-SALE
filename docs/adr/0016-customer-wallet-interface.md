# ADR 0016: Customer wallet interface

## Status
Accepted for Milestone 3-A2A.

## Decision
Customer-web renders wallet information through focused client modules for API access, runtime validation, money formatting, bucket/status mapping and React presentation. Backend wallet APIs remain authoritative for ownership, balances, policy, history, credit lots and reservations. The frontend never mutates balances, never stores wallet responses in browser storage, and never exposes ledger account internals.

## Consequences
The wallet UI can be used in Telegram Mini App and browser fallback flows without adding checkout or payment functionality. Future payment milestones must add separate routes and backend commands rather than extending this read-only interface into a mutation surface.
