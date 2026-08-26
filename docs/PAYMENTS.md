# Card-to-card payments and wallet

The production commerce boundary is intentionally card-to-card only. There is no
Zarinpal, gateway callback, public payment-intent, provider webhook, automatic capture
or automatic refund route in the mounted application.

1. An administrator publishes an active card destination. Customer projections expose
   only the bounded display fields needed to make a transfer.
2. A customer creates a manual top-up request in the website, Telegram Mini App or bot.
3. The customer uploads an image receipt. The backend validates size/type, re-encodes
   it, removes metadata, generates a private filename and never exposes a storage path.
4. An authorized administrator reviews the immutable receipt, records the verified
   amount and optional bonus, and approves or rejects it with a reason.
5. Approval and the wallet ledger entry commit atomically and idempotently. Money is
   stored as integer rial; UI conversion to toman happens only at presentation edges.
6. Product checkout debits the wallet. Cancellation/refund creates compensating ledger
   entries; operators never edit a balance directly.

Receipt lifecycle: `AWAITING_SUPPORT`, `AWAITING_RECEIPT`, `UNDER_REVIEW`,
`NEEDS_RESUBMISSION`, `APPROVED`, `REJECTED`, `CANCELLED`, `EXPIRED`.

The destination must be configured and activated before requests are accepted. Keep
receipt storage on the private persistent volume, include it in encrypted backups, and
grant review/approval permissions only to finance operators. Do not add gateway secrets
to production environment files: online gateways are outside this release.
