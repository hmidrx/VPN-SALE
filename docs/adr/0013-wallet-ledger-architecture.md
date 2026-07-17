# ADR 0013: Wallet and double-entry ledger architecture

## Status
Accepted for Milestone 3-A1.

## Decision
Wallet value is represented as platform liability. A **credit** posting to a customer wallet liability account increases customer-facing positive balance; a **debit** posting decreases it. Every posted journal has at least two positive integer-rial postings and total debits equal total credits. Journal entries and postings are append-only in repositories; corrections use reversal entries.

System accounts introduced now are payment clearing, order reservation clearing, admin adjustment expense/recovery, promotional expense, and refund clearing. No payment, order, provider, checkout, or provisioning command is implemented.

## Consequences
The ledger is authoritative. Cached projections support reads but reconciliation can rebuild them from postings and active reservations without inventing money.
