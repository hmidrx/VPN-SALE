# Manual card-transfer top-ups (PAY-1 foundation)

Manual top-ups are reviewed financial evidence, not online-provider payments. The feature is
disabled by default. Authoritative amounts are integer rial; customer surfaces convert exactly to
Toman. Requested, verified-transfer, bonus, and total-credit amounts remain separate. Approval
posts the verified amount to `CASH` and any explicitly authorized bonus to `ADMIN_GRANT` through
the wallet ledger. Upload and review states never mutate wallet balances.

## Lifecycle and authorization

Requests move from awaiting support/receipt to review, resubmission, approval, or rejection.
Approved, rejected, cancelled, and expired records are historical terminal evidence. Review uses
an expected version and row lock. Approval additionally requires the review and wallet-adjustment
permissions, CSRF, an idempotency key, and a short-lived one-use strong confirmation. Amount
differences and bonuses also require the override permission and a recorded reason. Corrections are
new ledger adjustments; an approved request is never edited back.

## Private evidence

`LOCAL_PRIVATE` storage streams to a hard 5 MiB limit, accepts JPEG/PNG/WebP only after magic and
decode verification, rejects animation and unsafe dimensions, removes metadata by re-encoding,
and stores a generated name with mode `0600` below a mode `0700` private root. Bytes remain outside
PostgreSQL and outside public web roots. Receipt responses must be authenticated streams with
verified content type, `nosniff`, and attachment disposition. Duplicate sanitized hashes are a
review warning only and are not proof of fraud.

## Destination separation

This module stores no transfer destination or banking identity. Customer interfaces offer
«دریافت شماره کارت از پشتیبانی» and may open support with only the opaque request reference.
Receipt submission is independent of support persistence. Customer-visible review messages reject
destination-like digit sequences, preventing the review timeline from becoming an alternate
delivery channel. Full support persistence is deferred.

## Rollout and rollback

Roll out schema revision `0032_manual_card_topups`, provision a private persistent upload volume,
then explicitly enable `VPN_SALE_MANUAL_CARD_TOPUPS_ENABLED`. Keep online-provider writes and fake
payment success disabled. Back up database rows and the private evidence volume together.

Rollback first disables the feature so new mutations fail closed. Application rollback preserves
requests, evidence, decisions, notifications, and all wallet journal entries. Schema downgrade is
only appropriate when no retained PAY-1 data is required; it must never be used to reverse a posted
wallet credit.

## PAY-1B backend contract

The authenticated customer API exposes create/list/detail, multipart receipt replacement, private
receipt streaming, and pre-review cancellation under `/api/v1/customer/manual-topups`. Mutation
requests require CSRF, a bounded fail-closed rate check, the disabled-by-default feature flag, and
an `Idempotency-Key`; reads remain available while the flag is disabled so customers retain access
to historical evidence. Ownership always comes from the authenticated customer session.

The protected admin API exposes the review queue/detail/receipt and resubmission, rejection,
approval, and durable-message mutations under `/api/v1/admin/manual-topups`. Permissions are
`manual_topups.read`, `manual_topups.review`, `manual_topups.message`, and
`manual_topups.override_amount`; approval also requires `wallets.adjust`. These permissions are
registered but are not assigned automatically to any administrator role. Operators must explicitly
assign them to a locally designated high-trust finance role.

Approval consumes a hash-only, session/purpose/reference-bound confirmation obtained with the
administrator's password and enrolled TOTP (or one-use recovery proof). It expires after five
minutes. Override confirmation also binds the acknowledgement. The request, confirmation,
idempotency record, immutable decision, messages, pending notification, audit row, CASH journal,
optional separate ADMIN_GRANT journal, postings, and wallet projections share the request-scoped
PostgreSQL transaction. An exception rolls all database effects back; sanitized upload files are
removed when database persistence fails.

Revision `0033_manual_topup_application` removes the decision-kind uniqueness defect in the PAY-1
foundation so multiple legitimate resubmission cycles can retain immutable decisions, and registers
the four permissions. Downgrade restores the constraint and removes only these permission rows; it
will intentionally fail if repeated decision history must first be retained. Deploy 0033, provision
the mode-0700 evidence volume, explicitly assign permissions, verify Redis and PostgreSQL, then
enable `VPN_SALE_MANUAL_CARD_TOPUPS_ENABLED` for a controlled cohort. Roll back by disabling the
flag before rolling back application code; never downgrade or delete posted ledger evidence as a
financial reversal.

No destination card number, IBAN, payment-provider success path, public receipt URL, or fake payment
settlement is stored or exposed. Customer/admin visual redesign, native Telegram photo intake, and
the notification delivery worker are explicitly deferred. Outbox rows therefore remain `PENDING`
until that worker is safely delivered. PAY-1 is not yet claimed as fully customer-usable.
