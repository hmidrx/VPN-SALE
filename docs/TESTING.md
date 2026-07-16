# Testing

Testing strategy covers unit, integration, contract, adapter, pricing, wallet concurrency, ledger invariants, order state machines, provisioning idempotency, reconciliation, RBAC, object auth, Telegram handlers, notification dedupe, migrations, browser E2E, accessibility, load, backup/restore, failover, and security regression tests.

## Milestone 0 verification

Milestone 0 uses GitHub Actions as the authoritative verification environment. The main workflow `.github/workflows/verify.yml` runs backend, frontend, Docker Compose, and security jobs on Ubuntu with Python 3.12, Node.js 22, PostgreSQL 16, Redis 7, and Docker Compose v2.

Repository scripts mirror CI categories and are intended for Codespaces and CI reuse:

- `scripts/verify-backend.sh`
- `scripts/verify-frontend.sh`
- `scripts/verify-docker.sh`
- `scripts/security-scan.sh`
- `scripts/verify-all.sh`

The current no-lockfile npm installation path is temporary. Once `package-lock.json` is generated in Codespaces and committed, CI and Codespaces should use `npm ci` for reproducible frontend installs.


## Pyright environment policy

Pyright no longer hard-codes `.venv` in `pyproject.toml`. CI uses the Python 3.12 interpreter provided by `actions/setup-python`, while Codespaces and repository scripts source `.venv` when it exists. Import roots are declared through Pyright `extraPaths`, and `apps/api/src/platform_api/py.typed` marks the local API package as typed. This avoids CI-only `.venv` path warnings without disabling type checking.

## Security scanner regression coverage

`scripts/test-security-scan.sh` verifies that the scanner passes a safe repository state, fails for a staged temporary secret fixture, does not report its own deliberate regex definitions, and does not print secret values.
