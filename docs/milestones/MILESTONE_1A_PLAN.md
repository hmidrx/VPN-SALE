# Milestone 1A Plan: Identity Data Foundation

## Scope
Milestone 1A establishes framework-independent identity domain entities, legal account status state machines, SQLAlchemy persistence, repository implementations, Alembic schema, RBAC seed data, audit/security event foundations, and cryptographic primitives for passwords, opaque tokens, and key-versioned encrypted secrets.

## Non-goals
No login endpoints, refresh endpoints, cookies, CSRF, Telegram authentication verification, admin bootstrap command, MFA enrollment, frontend authentication pages, commerce, wallets, payments, panel provisioning, subscriptions, or real external integrations are included.

## Assumptions
- Internal user UUIDs are independent from Telegram user identifiers.
- PostgreSQL is the production database; tests may use SQLite-compatible metadata checks where useful.
- Initial permissions and roles are seeded by an explicit idempotent command/helper, not by creating an administrator in migrations.
- Development encryption keys are disposable and never production secrets.

## Security risks and controls
- Plaintext credentials are prohibited; only password hashes, refresh-token hashes, recovery-code hashes, and encrypted TOTP secret placeholders are persisted.
- Audit metadata rejects secret-looking keys and values before append.
- Argon2id parameters are configurable and support `needs_rehash`.
- Opaque token verification uses constant-time comparison.
- Encrypted secret records include a key version for future rotation.

## Acceptance criteria
- Domain entities and status transitions are covered by unit tests.
- Identity schema migrations upgrade, downgrade, and re-upgrade on a disposable database.
- Unique constraints cover normalized admin email, Telegram ID, permissions, roles, role-permission pairs, admin-role pairs, session token hashes, and recovery-code hashes.
- Repository interfaces return domain objects and do not expose SQLAlchemy ORM models.
- Documentation describes schema, status transitions, seed mechanism, and known limitations.
