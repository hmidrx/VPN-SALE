# Phase 1A.2.3 — unified web and Telegram account access

## Scope and trust boundaries

One `identity_users` row remains the customer account and owns all services, wallet entries,
orders, roles, support history, and sessions. This phase only attaches authentication methods;
it never copies or moves business records. Telegram numeric identity is accepted only from
fresh, server-verified `initData`. Usernames, profile similarity, browser Telegram objects,
query-string user IDs, IP addresses, and user agents are never identity evidence.

Web-first customers reauthenticate with their current password and CSRF-protected session. The
API returns a random, ten-minute challenge whose salted hash—not the raw value—is stored. A
Telegram-signed `start_param` binds the Mini App completion to that challenge. Completion locks
and consumes the challenge and enforces both one-to-one ownership rules in the same transaction,
then issues a normal customer session for the existing account.

Telegram-first customers may enroll the existing password policy's username and Argon2id
credential only after fresh `initData` matches the Telegram identity already attached to the
current authenticated account. Enrollment never creates an identity and cannot replace an
existing credential. Public anonymous registration remains independent.

## Conflicts and duplicate accounts

There is no automatic merge. An already-owned Telegram identity, a target with another Telegram
identity, an existing credential, and username uniqueness collisions all return a generic
conflict. No merge is inferred from Telegram username, email, name, phone, IP, user agent, or
profile data. Resolution of already-populated duplicate accounts is deferred to an explicit,
administrator-reviewed workflow.

## Unlink and sessions

Unlink requires CSRF, current-password reauthentication, an existing credential, an attached
Telegram identity, and enabled password login. It sets Telegram ownership to `NULL`, preserves
all customer data, revokes every central-account session with reason `telegram_unlink`, clears
the refresh cookie, and requires password sign-in. A later ordinary Telegram login creates a
new Telegram-only identity by safely reclaiming the unowned Telegram row; it cannot regain the
old web account.

## Persistence, observability, and cleanup

Migration `0030_telegram_link_challenges` adds the ephemeral challenge table, expiry and cleanup
indexes, ownership/session foreign keys, failed-attempt count, and consumption timestamp. Raw
challenges and identity attributes are excluded from audit/security metadata. Stable event codes
record challenge creation, success, generic failure/conflict, enrollment, and unlink outcomes.
Expired rows can be deleted by `expires_at`; downgrade safely drops only this ephemeral table.
The feature model lives in `customer_auth.models`, outside the identity module imported during
historical upgrades. Alembic imports it only for autogenerate discovery, so revision 0030 alone
creates the table. PostgreSQL lifecycle verification covers 0029 → 0030, a repeated no-op
upgrade, downgrade to 0029, and re-upgrade while checking identity ownership is unchanged.

Challenge creation locks the stable central-user row before replacing an active challenge.
Completion locks the challenge and both ownership sides, and uses a savepoint so a uniqueness
race rolls back only the attempted link before its sanitized failure event is persisted. An
unowned Telegram row is locked before ordinary authentication may reclaim it. Credential
enrollment and unlink password checks share bounded user, session, and IP rate limits.

## Rollout and rollback

`telegram_account_linking_enabled` remains false in repository and deployment defaults. Routes
are registered only when it is true, so disabled endpoints are absent from OpenAPI and resolve
404 before database, Redis, hashing, or Telegram-verifier dependencies run. Password login is
also required before credential enrollment is advertised or unlink is allowed. Roll out the
migration first, enable password login where intended, then enable linking. To roll back, disable
linking, drain requests, remove expired challenges, and downgrade 0030; existing identity links
and credentials are intentionally retained because rollback must not rewrite customer data.
