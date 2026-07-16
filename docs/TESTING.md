# Testing

Testing strategy covers unit, integration, contract, adapter, pricing, wallet concurrency, ledger invariants, order state machines, provisioning idempotency, reconciliation, RBAC, object auth, Telegram handlers, notification dedupe, migrations, browser E2E, accessibility, load, backup/restore, failover, and security regression tests.

## Milestone 0 verification

Milestone 0 uses GitHub Actions as the authoritative verification environment. The main workflow `.github/workflows/verify.yml` runs backend, frontend, Docker Compose, and security jobs on Ubuntu with Python 3.12, Node.js 22, PostgreSQL 16, Redis 7, and Docker Compose v2.

Repository scripts mirror CI categories and are intended for Codespaces and CI reuse. Backend verification derives the CI application database URL from the disposable PostgreSQL service credentials and verifies those credentials with a sanitized preflight before Alembic runs. Frontend verification reports tool versions and runs each real Next.js production build under a clear workspace label:

- `scripts/verify-backend.sh`
- `scripts/verify-frontend.sh`
- `scripts/verify-docker.sh`
- `scripts/security-scan.sh`
- `scripts/verify-all.sh`

The current no-lockfile npm installation path is temporary. Missing `package-lock.json` is a security-scan warning, not a failure, during this phase. When frontend CI falls back to `npm install`, it uploads the generated `package-lock.json` as the `generated-package-lock` artifact and does not commit or push it. Once `package-lock.json` is generated in Codespaces and committed, CI and Codespaces should use `npm ci` for reproducible frontend installs.

Security regression coverage is provided by `scripts/test-security-scan.sh`. It checks that the safe repository state passes, a temporary fake secret fixture fails, scanner pattern definitions do not self-match, and secret values are not printed.
