# ADR 0060: encrypted, request-scoped manual top-up destinations

## Decision
Manual card-transfer destinations are immutable encrypted versions. The existing identity Fernet key and its key-version metadata protect both the normalized card number and optional holder name; plaintext is never persisted. A singleton settings row selects the active version and controls global customer visibility with optimistic concurrency.

A request snapshots the active version only when display is enabled. It starts in `AWAITING_RECEIPT`; otherwise it remains fully usable in support-only `AWAITING_SUPPORT` mode. Replacement never changes old snapshots. Disabling visibility immediately makes every customer destination response support-only, while re-enabling reveals only each request's original snapshot.

Ordinary administration returns a mask and requires dedicated read permission. Every mutation requires dedicated high-trust management permission, password/TOTP strong confirmation bound to session and intended mutation, CSRF, rate limiting, idempotency, and an expected settings version. Audit metadata contains references and state only.

The full destination is available only through the authenticated ownership-checked request endpoint with private/no-store headers. It is excluded from public runtime configuration, ordinary request DTOs, notifications, Telegram payloads, URLs, and browser storage.

## Rollout and rollback
Deploy application code with revision `0035_manual_topup_destinations`, configure no new secret, grant destination permissions only to intended high-trust roles, register a synthetic/approved production destination through the admin flow, then explicitly enable display. Until enabled, support-only operation continues.

Rollback first disables customer display, then rolls application code back. Downgrade to 0034 only after confirming destination history is no longer required; the downgrade removes only the new foreign key, settings, and encrypted version tables. Database backup and audit retention procedures still apply.
