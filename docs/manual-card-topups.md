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
