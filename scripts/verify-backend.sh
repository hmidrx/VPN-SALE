#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }
if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
export VPN_SALE_ENVIRONMENT="test"
export VPN_SALE_VERSION="ci-milestone0"
export VPN_SALE_DATABASE_URL="${VPN_SALE_DATABASE_URL:-postgresql+asyncpg://vpnsale:vpnsale_ci_password@localhost:5432/vpnsale_test}"
export VPN_SALE_REDIS_URL="${VPN_SALE_REDIS_URL:-redis://localhost:6379/0}"
export PYTHONPATH="apps/api/src:apps/telegram-bot/src:apps/worker/src:packages/domain/src:packages/panel-adapters/src:packages/payment-adapters/src:${PYTHONPATH:-}"

log "Python and tool versions"
python --version
python -m pip --version
ruff --version
pyright --version
pytest --version
alembic --version

log "Python formatting"
ruff format --check .
log "Python linting"
ruff check .
log "Python typing"
pyright
log "Pytest"
mkdir -p test-reports
pytest --junitxml=test-reports/backend-pytest.xml
log "Alembic upgrade/current/downgrade/re-upgrade"
alembic -c apps/api/alembic.ini upgrade head
alembic -c apps/api/alembic.ini current
alembic -c apps/api/alembic.ini downgrade base
alembic -c apps/api/alembic.ini upgrade head
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
