# Payments

Provider-independent PaymentProvider supports create, verify, webhook handling, status, cancel, refund, reconciliation, health, and fees. Milestone 0 includes contracts/fakes only: WalletPaymentProvider, FakePaymentProvider, ManualReceiptProvider, TelegramStarsPaymentProvider are planned.

## Milestone 4-A1 provider-neutral payment core
The payment core is provider-neutral and versioned. It introduces payment method registry records, immutable intents and attempts, verification records, exactly-once settlements, webhook inbox records, refund records, idempotency records and reconciliation runs. Only a deterministic fake adapter exists for automated tests and explicit development; production registry construction rejects it. Browser returns are never authoritative proof of payment; server-side verification and exact IRR amount matching are required before settlement.

## Milestone 4-A2B1 administrator payment operations
Admin payment operations are exposed in admin-web under `/management/payments`, `/management/payment-methods`, `/management/payment-intents`, `/management/payment-attempts`, `/management/payment-settlements`, and `/management/payment-webhooks`. The console is read-heavy, Persian RTL, and uses real backend payment APIs only. Method management edits non-sensitive policy/localization and sends reviewed lifecycle commands; it never configures gateway secrets in the browser. Intent amount/purpose, attempt verification results and settlement journals are immutable. Webhook detail renders sanitized metadata only; raw bodies and signatures are not available in the UI. Refund administration and reconciliation repair remain open for Milestone 4-A2B2.
