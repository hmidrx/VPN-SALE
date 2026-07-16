# Database

PostgreSQL is the source of truth. UUIDs are used for public identifiers; UTC timestamps are mandatory. Integrity uses unique constraints, foreign keys, check constraints, idempotency-key uniqueness, ledger balancing constraints, and indexes on tenant, status, timestamps, provider references, and reconciliation fields. Retention policies are configurable by data class.
