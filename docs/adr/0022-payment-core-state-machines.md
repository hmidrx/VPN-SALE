# ADR 0022: Payment core state machines and settlement boundaries

## Status
Accepted for Milestone 4-A1.

## Decision
Payment intents and attempts use explicit legal transitions. Browser returns only move attempts toward verification; success requires trusted server-side verification and exact amount/currency matching. Settlements are recorded once per intent and reference immutable ledger journals. Refunds use compensating journals rather than editing original settlement or ledger entries.

## Consequences
Expired or cancelled intents that later receive provider success evidence move to reconciliation-required review rather than silently crediting wallets or marking invoices paid.
