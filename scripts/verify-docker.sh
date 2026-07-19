#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }; }
need_cmd docker
need_cmd curl
need_cmd jq
cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    docker compose logs --no-color api reverse-proxy postgres redis || true
  fi
  docker compose down --volumes --remove-orphans || true
  exit $status
}
trap cleanup EXIT

log "Docker versions"
docker --version
docker compose version
log "Compose config"
docker compose config

log "Test-server Compose port isolation"
"$repo_root/scripts/verify-test-server-compose.sh"
log "Build core images"
docker compose build api
log "Start core stack"
docker compose up -d postgres redis api reverse-proxy
log "Wait for proxy endpoints"
scripts/wait-for-http.sh http://localhost:8080/health 90
scripts/wait-for-http.sh http://localhost:8080/version 90
scripts/wait-for-http.sh http://localhost:8080/metrics 90
scripts/wait-for-http.sh http://localhost:8080/ready 90
log "Compose status"
docker compose ps
log "Verify endpoint responses"
health="$(curl --fail --silent http://localhost:8080/health)"
ready="$(curl --fail --silent http://localhost:8080/ready)"
version="$(curl --fail --silent http://localhost:8080/version)"
metrics="$(curl --fail --silent http://localhost:8080/metrics)"
printf '%s' "$health" | jq -e '.status == "ok"' >/dev/null
printf '%s' "$ready" | jq -e '.status == "ready" and .checks.database == true and .checks.redis == true' >/dev/null
printf '%s' "$version" | jq -e '.version and .environment' >/dev/null
printf '%s' "$metrics" | grep -q 'vpnsale_api_info'
combined="$health$ready$version$metrics"
if printf '%s' "$combined" | grep -Eiq '(password|secret|token|cookie|vless://|vmess://|trojan://)'; then
  echo "Endpoint response contained a forbidden sensitive marker." >&2
  exit 1
fi
log "Docker stack verification passed"
