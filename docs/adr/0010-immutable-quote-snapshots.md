# ADR 0010: Immutable Quote Snapshots

## Status
Accepted for Milestone 2-A.

## Decision
Customer quotes persist product version ID, selected options, price-list version ID, components, final integer amount, issue/expiration timestamps and pricing-engine version. Recalculation creates a new quote. Idempotency keys are customer-scoped and fingerprinted.

## Consequences
Future orders can rely on the stored quote amount without trusting client prices or recalculating historical pricing.
