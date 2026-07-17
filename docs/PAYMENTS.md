# Payments

Provider-independent PaymentProvider supports create, verify, webhook handling, status, cancel, refund, reconciliation, health, and fees. Milestone 0 includes contracts/fakes only: WalletPaymentProvider, FakePaymentProvider, ManualReceiptProvider, TelegramStarsPaymentProvider are planned.

## Milestone 4-A1 provider-neutral payment core
The payment core is provider-neutral and versioned. It introduces payment method registry records, immutable intents and attempts, verification records, exactly-once settlements, webhook inbox records, refund records, idempotency records and reconciliation runs. Only a deterministic fake adapter exists for automated tests and explicit development; production registry construction rejects it. Browser returns are never authoritative proof of payment; server-side verification and exact IRR amount matching are required before settlement.
