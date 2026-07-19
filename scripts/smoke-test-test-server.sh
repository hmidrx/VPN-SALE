#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${VPN_SALE_TEST_SERVER_ENV_FILE:-/opt/vpn-sale-runtime/test.env}"
compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$env_file")
"${compose[@]}" ps --format json | jq -e 'all(.RestartCount == 0)' >/dev/null
"${compose[@]}" config --format json | jq -e '.services.worker == null or (.services.worker.profiles // [] | index("ops"))' >/dev/null
curl -fsS http://127.0.0.1:8000/health >/dev/null
curl -fsS http://127.0.0.1:8000/ready >/dev/null
for port in 3000 3001 3002; do curl -fsS "http://127.0.0.1:$port" >/dev/null; done
ss -ltn | grep -Eq ':(5432|6379)\b' && { echo 'database/redis port is public or bound on host' >&2; exit 1; } || true
if systemctl is-active --quiet caddy; then caddy validate --config /etc/caddy/Caddyfile; fi
if grep -q '^VPN_SALE_BOT_ENABLED=true' "$env_file"; then
  "${compose[@]}" ps telegram-bot --format json | jq -e '.RestartCount == 0 and .State == "running"' >/dev/null
fi
printf 'test-server smoke checks passed\n'
