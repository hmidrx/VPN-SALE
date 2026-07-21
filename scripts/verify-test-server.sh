#!/usr/bin/env bash
set -euo pipefail
DOMAIN=""; ENV_FILE="${VPN_SALE_TEST_SERVER_ENV_FILE:-/opt/vpn-sale-runtime/test.env}"; RUNTIME_DIR="/opt/vpn-sale-runtime"
while [[ $# -gt 0 ]]; do case "$1" in --domain) DOMAIN="${2:?}"; shift 2;; --env-file) ENV_FILE="${2:?}"; shift 2;; --runtime-dir) RUNTIME_DIR="${2:?}"; shift 2;; *) echo "unknown option $1" >&2; exit 64;; esac; done
[[ -n "$DOMAIN" ]] || { echo "--domain is required" >&2; exit 64; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-compose-json.sh
source "$repo_root/scripts/test-server-compose-json.sh"
# shellcheck source=scripts/test-server-installer-lib.sh
source "$repo_root/scripts/test-server-installer-lib.sh"
compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$ENV_FILE")
ok(){ printf 'OK: %s\n' "$*"; }
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
[[ -f "$RUNTIME_DIR/state.json" ]] && jq -e --arg d "$DOMAIN" '.environment=="TEST" and .root_domain==$d and .compose_project=="vpn-sale"' "$RUNTIME_DIR/state.json" >/dev/null || fail "runtime state mismatch"
ok "runtime state is TEST for $DOMAIN at commit $(jq -r '.selected_commit' "$RUNTIME_DIR/state.json")"
"$repo_root/scripts/verify-test-server-compose.sh" "$ENV_FILE" >/dev/null; ok "Compose config renders with expected services/profiles"
for svc in postgres redis; do [[ "$(compose_service_field "$svc" Health "${compose[@]}")" == healthy ]] || fail "$svc not healthy"; ok "$svc healthy"; done
pg_user="$(get_env POSTGRES_USER "$ENV_FILE")"; pg_db="$(get_env POSTGRES_DB "$ENV_FILE")"
"${compose[@]}" exec -T postgres pg_isready -U "$pg_user" -d "$pg_db" >/dev/null || fail "PostgreSQL readiness failed for configured role/database"; ok "PostgreSQL accepts configured user/database"
"${compose[@]}" run --rm --no-deps api alembic -c apps/api/alembic.ini current >/dev/null; ok "Alembic migration state readable"
for url in http://127.0.0.1:8000/ready http://127.0.0.1:3000 http://127.0.0.1:3001 http://127.0.0.1:3002; do curl -fsS --max-time 10 "$url" >/dev/null || fail "local HTTP failed: $url"; ok "local HTTP $url"; done
systemctl is-active --quiet caddy || fail "caddy inactive"; caddy validate --config /etc/caddy/Caddyfile >/dev/null; is_managed_caddyfile /etc/caddy/Caddyfile || fail "Caddyfile is not installer-managed"; ! grep -Fq 'fast.dr-ping.com' /etc/caddy/Caddyfile || fail "forbidden fast.dr-ping.com in Caddyfile"; ok "managed Caddy active and validates"
for p in 80 443; do ss -ltnp "sport = :$p" | grep -Fq caddy || fail "port $p not owned by managed Caddy"; ok "port $p owned by Caddy"; done
for bind in '127.0.0.1:8000' '127.0.0.1:3000' '127.0.0.1:3001' '127.0.0.1:3002'; do ss -ltn | grep -Fq "$bind" || fail "missing loopback binding $bind"; ok "$bind loopback-bound"; done
"${compose[@]}" config --format json | jq -e '(.services.postgres.ports // []) == [] and (.services.redis.ports // []) == [] and (.services.worker.ports // []) == [] and (.services["telegram-bot"].ports // []) == []' >/dev/null || fail "private services publish ports"; ok "PostgreSQL/Redis/worker/Telegram publish no ports"
for u in "https://app.$DOMAIN" "https://api.$DOMAIN/health" "https://admin.$DOMAIN" "https://reseller.$DOMAIN"; do curl -fsS --max-time 20 "$u" >/dev/null || fail "HTTPS smoke failed: $u"; ok "HTTPS $u"; done
if [[ "$(get_env VPN_SALE_BOT_ENABLED "$ENV_FILE")" == true ]]; then compose_service_field telegram-bot State "${compose[@]}" >/dev/null || fail "telegram bot container missing"; ok "Telegram bot container present (identity derived from getMe during install)"; fi
systemctl is-active --quiet fail2ban || fail "fail2ban inactive"; ok "fail2ban active"
swapon --show --noheadings | grep -q . || fail "swap missing"; ok "swap present"
! rg -n 'fast\.dr-ping\.com' "$RUNTIME_DIR" /etc/caddy/Caddyfile >/dev/null || fail "fast.dr-ping.com present in generated deployment configuration"; ok "fast.dr-ping.com absent from generated deployment configuration"
printf 'Verification completed without exposing secrets.\n'
