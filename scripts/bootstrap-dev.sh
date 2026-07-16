#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }; }

log "Validating runtimes"
need_cmd python3
need_cmd node
need_cmd npm
python_version="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
if [[ "$python_version" != "3.12" ]]; then
  if command -v python3.12 >/dev/null 2>&1; then
    python_bin="python3.12"
  else
    echo "Python 3.12 is required; found python3 ${python_version}." >&2
    exit 1
  fi
else
  python_bin="python3"
fi
node_major="$(node -p 'process.versions.node.split(`.`)[0]')"
if [[ "$node_major" != "22" ]]; then
  echo "Node.js 22 is required; found $(node --version)." >&2
  exit 1
fi
npm --version

log "Preparing Python virtual environment"
if [[ ! -d .venv ]]; then
  "$python_bin" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python --version
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements-dev.txt

log "Preparing Node dependencies"
if [[ -f package-lock.json ]]; then
  npm ci
else
  echo "::warning::package-lock.json is absent; running npm install temporarily. Commit the generated lockfile for reproducible installs."
  npm install
  if [[ -f package-lock.json ]]; then
    cat <<'MSG'
package-lock.json was generated. Review and commit it with:
  git add package-lock.json
  git commit -m "Add reproducible frontend dependency lockfile"
  git push
MSG
  fi
fi

log "Preparing safe local environment"
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from safe local placeholders."
else
  echo ".env already exists; leaving it unchanged."
fi

log "Validating Docker availability"
need_cmd docker
docker --version
docker compose version

cat <<'MSG'

Next commands:
  scripts/verify-backend.sh
  scripts/verify-frontend.sh
  scripts/verify-docker.sh
  scripts/verify-all.sh
  docker compose up --build api reverse-proxy
MSG
