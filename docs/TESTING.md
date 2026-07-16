# Testing

Testing strategy covers unit, integration, contract, adapter, pricing, wallet concurrency, ledger invariants, order state machines, provisioning idempotency, reconciliation, RBAC, object auth, Telegram handlers, notification dedupe, migrations, browser E2E, accessibility, load, backup/restore, failover, and security regression tests.

## Milestone 0 verification

Milestone 0 uses GitHub Actions as the authoritative verification environment. The main workflow `.github/workflows/verify.yml` runs backend, frontend, Docker Compose, and security jobs on Ubuntu with Python 3.12, Node.js 22, PostgreSQL 16, Redis 7, and Docker Compose v2.

Repository scripts mirror CI categories and are intended for Codespaces and CI reuse. Backend verification derives the CI application database URL from the disposable PostgreSQL service credentials and verifies those credentials with a sanitized preflight before Alembic runs. Frontend verification reports tool versions, gates npm dependency security with `npm audit --audit-level=high`, and runs each real Next.js production build under a clear workspace label:

- `scripts/verify-backend.sh`
- `scripts/verify-frontend.sh`
- `scripts/verify-docker.sh`
- `scripts/security-scan.sh`
- `scripts/verify-all.sh`

The current no-lockfile npm installation path is temporary. Missing `package-lock.json` is a security-scan warning, not a failure, during this phase. When frontend CI falls back to `npm install`, it uploads the generated `package-lock.json` as the `generated-package-lock` artifact and does not commit or push it. Once `package-lock.json` is generated in Codespaces and committed, CI and Codespaces should use `npm ci` for reproducible frontend installs.

Security regression coverage is provided by `scripts/test-security-scan.sh`. It checks that the safe repository state passes, a temporary fake secret fixture fails, scanner pattern definitions do not self-match, and secret values are not printed.

## Frontend dependency security remediation

The July 2026 Milestone 0 dependency remediation upgraded the web apps from `next@15.1.3`, `react@19.0.0`, and `react-dom@19.0.0` to patched `next@15.5.20`, `react@19.2.7`, and `react-dom@19.2.7`, with Node type packages updated to the Node 22 line and React type packages kept on the compatible 19.0.x line required by Next.js 15.5 generated validator types. Validation commands executed for the remediation include `npm ci`, `npm audit`, workspace lint/typecheck/test, the three real Next.js production builds, backend Ruff/Pyright/pytest checks, the repository security scan, the security scanner regression test, and `git diff --check`. Remaining moderate npm audit risk is documented in `docs/SECURITY.md`.

## Milestone 1A tests

Milestone 1A adds deterministic unit tests for identity state machines, normalization, permission-code validation, audit metadata rejection, Argon2id, opaque tokens, and encrypted secrets. Integration-style tests exercise SQLite-backed SQLAlchemy metadata for repository behavior, uniqueness constraints, RBAC seed idempotency, append-only audit insertion, and refresh-token hash persistence. PostgreSQL Alembic upgrade/downgrade/re-upgrade remains required for final CI or a disposable local database.

## Milestone 1B-A tests

Added deterministic tests for password policy, bootstrap, generic login failures, lockout events, access-token validation, hardened rate-limit keys, refresh rotation/reuse family revocation, TOTP enrollment, MFA challenge login, recovery-code hashing, and one-time recovery-code rejection.

## Milestone 1B-B tests

Backend tests cover CSRF validation, safe profile/session data, password change with other-session revocation, cross-admin session ownership denial, recovery-code regeneration, and MFA disablement. Admin frontend tests assert memory-only access-token storage, credentials-enabled refresh calls, Authorization headers, and refresh single-flight control.

## Milestone 1C-A customer authentication note
Customer Telegram Mini App authentication now verifies raw init data, links Telegram identities to internal customers, issues isolated customer access credentials, rotates opaque refresh-cookie sessions, enforces CSRF on cookie-authenticated state changes, rate limits sensitive operations, and records sanitized audit/security events. Commerce and customer UI remain out of scope.
## Milestone 1C-B1 tests
Customer frontend checks cover Telegram adapter safety, absence of `initDataUnsafe`, memory-only credential storage, CSRF/credentials-enabled requests, single-flight refresh, one-time retry, bootstrap deduplication, browser fallback text, RTL/LTR rendering hooks, safe-area styling, and absence of commerce vocabulary. Full browser E2E should run in CI with the explicit fake Telegram adapter and signed backend fixture.
