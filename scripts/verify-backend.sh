#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
export VPN_SALE_ENVIRONMENT="test"
export VPN_SALE_VERSION="ci-milestone0"
export POSTGRES_DB="${POSTGRES_DB:-vpnsale_test}"
export POSTGRES_USER="${POSTGRES_USER:-vpnsale}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required for backend verification}"
export POSTGRES_PASSWORD
export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export VPN_SALE_DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
export VPN_SALE_REDIS_URL="${VPN_SALE_REDIS_URL:-redis://127.0.0.1:6379/0}"
export PYTHONPATH="apps/api/src:apps/telegram-bot/src:apps/worker/src:packages/domain/src:packages/panel-adapters/src:packages/payment-adapters/src:${PYTHONPATH:-}"

log "Python and tool versions"
python --version
python -m pip --version
ruff --version
pyright --version
pytest --version
alembic --version

log "PostgreSQL credential preflight"
python - <<'PY'
import asyncio
import os
from urllib.parse import urlsplit

import asyncpg

url = os.environ["VPN_SALE_DATABASE_URL"]
parts = urlsplit(url)
expected_host = os.environ["POSTGRES_HOST"]
expected_db = os.environ["POSTGRES_DB"]
expected_user = os.environ["POSTGRES_USER"]
if parts.hostname != expected_host or parts.path.lstrip("/") != expected_db or parts.username != expected_user:
    raise SystemExit(
        "Database URL does not match expected CI host, database, and user "
        f"(host={parts.hostname!r}, database={parts.path.lstrip('/')!r}, user={parts.username!r})."
    )

async def main() -> None:
    last_error = "unknown error"
    for attempt in range(1, 31):
        try:
            conn = await asyncpg.connect(
                host=expected_host,
                port=int(os.environ["POSTGRES_PORT"]),
                database=expected_db,
                user=expected_user,
                **{"password": os.environ["POSTGRES_PASSWORD"]},
                timeout=2,
            )
            try:
                await conn.execute("SELECT 1")
            finally:
                await conn.close()
            print(f"PostgreSQL credential preflight passed for host={expected_host} database={expected_db} user={expected_user}")
            return
        except Exception as exc:  # noqa: BLE001 - sanitized retry/failure boundary
            last_error = exc.__class__.__name__
            await asyncio.sleep(1)
    raise SystemExit(
        "PostgreSQL credential preflight failed for "
        f"host={expected_host} database={expected_db} user={expected_user}; last_error={last_error}"
    )

asyncio.run(main())
PY

log "Python formatting"
ruff format --check --diff .
log "Python linting"
ruff check .
log "Python typing"
pyright
log "Clean Alembic 0029/0030 lifecycle before tests"
if [[ "$VPN_SALE_ENVIRONMENT" != "test" || "$POSTGRES_DB" != *_test ]]; then
  printf 'Refusing destructive migration lifecycle outside a *_test database\n' >&2
  exit 1
fi
alembic -c apps/api/alembic.ini downgrade base
alembic -c apps/api/alembic.ini upgrade 0029_unified_account_schema
python - <<'PY'
import asyncio, os, asyncpg
async def main():
    conn = await asyncpg.connect(os.environ["VPN_SALE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    try:
        assert await conn.fetchval("SELECT to_regclass('public.telegram_link_challenges')") is None
    finally:
        await conn.close()
asyncio.run(main())
PY
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini current
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini downgrade 0029_unified_account_schema
alembic -c apps/api/alembic.ini upgrade head
log "Pytest"
mkdir -p test-reports
export VPN_SALE_RUN_MIGRATION_LIFECYCLE_TEST=1
pytest --junitxml=test-reports/backend-pytest.xml
log "Focused fulfillment/provider pytest"
pytest apps/worker/tests packages/panel-adapters/tests \
  --junitxml=test-reports/fulfillment-provider-pytest.xml
log "API import/startup smoke"
python - <<'PY'
from platform_api.main import app
routes = {route.path for route in app.routes}
required = {"/health", "/ready", "/version", "/metrics"}
missing = required - routes
if missing:
    raise SystemExit(f"Missing API routes: {sorted(missing)}")
print("API startup smoke passed")
PY
