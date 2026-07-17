# ADR 0021: Customer checkout interface

Customer-web implements Milestone 3-B2A as a thin, typed UI over the Milestone 3-B1 backend. The frontend validates response shapes and invoice totals, formats integer-rial values with labelled derived toman text, and renders order, financial and fulfillment statuses separately. It does not calculate authoritative prices, mutate balances, mark paid/ready locally, or expose provider/provisioning data.

Checkout idempotency is memory-only per deliberate operation. Duplicate clicks are suppressed; ambiguous failures preserve the same key/reference for recovery. Commerce data, auth data, CSRF values, raw Telegram initData and idempotency values are never written to browser storage.

The interface is wallet-only. External gateways, bank/card/crypto payments, mixed payments, provisioning, subscriptions, QR/config delivery and administrator order management remain future milestones.
