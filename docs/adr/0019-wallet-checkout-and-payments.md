# Milestone 3-B1 commerce ADR

## Status
Accepted for Milestone 3-B1.

## Decision
Orders are created only from active server-side quotes and keep immutable commercial snapshots. Checkout supports wallet funding only. Wallet reservations reduce available balance before confirmation; confirmation captures the reservation through balanced double-entry ledger postings. Issued invoice money and lines are immutable; cancellation records status changes and, after capture, a compensating wallet refund journal instead of editing the original capture.

## State and boundaries
Order, financial and fulfillment states are separate. The implemented happy path is `PAYMENT_RESERVED -> PAID -> READY_FOR_FULFILLMENT`, with unpaid cancellation to `CANCELLED` and paid pre-fulfillment compensation to `REFUNDED`. Routes are thin and call application helpers; order code imports catalog and wallet application/persistence adapters but never provider or payment-gateway adapters.

## Idempotency and concurrency
Checkout idempotency is scoped by customer, quote, operation and payment method. Raw keys are hashed and never returned. Quote conversion, checkout confirmation, reservation release/capture and admin cancellation use row locks and database uniqueness where practical.

## Future integration
`order.ready_for_fulfillment.v1` is written to the transactional outbox in the same transaction as the paid/ready transition. The payload contains normalized identifiers and safe requirements only. Allocation, provider choice, external gateways and provisioning consumers are future milestones.

## Milestone 3-B2B admin cancellation note
Administrator cancellation uses the reviewed backend cancellation command with stable memory-only idempotency. Reservation release and compensating wallet refund consequences are backend-authored; original captures remain immutable and no direct wallet balance setter or arbitrary refund control is exposed.
