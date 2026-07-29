#!/usr/bin/env bash
set -euo pipefail
usage(){ cat <<USAGE
Usage: scripts/verify-test-server.sh --domain DOMAIN [options]

Options:
  --domain DOMAIN        Root test domain to verify.
  --env-file FILE        Runtime env file (default: /opt/vpn-sale-runtime/test.env).
  --runtime-dir DIR      Runtime state directory (default: /opt/vpn-sale-runtime).
  --network-checks       Execute external DNS/HTTPS/ACME checks.
  --help                 Show this help and exit.
USAGE
}
NETWORK_CHECKS=false; DOMAIN=""; ENV_FILE="${VPN_SALE_TEST_SERVER_ENV_FILE:-/opt/vpn-sale-runtime/test.env}"; RUNTIME_DIR="/opt/vpn-sale-runtime"
while [[ $# -gt 0 ]]; do case "$1" in --help) usage; exit 0;; --domain) DOMAIN="${2:?}"; shift 2;; --env-file) ENV_FILE="${2:?}"; shift 2;; --runtime-dir) RUNTIME_DIR="${2:?}"; shift 2;; --network-checks) NETWORK_CHECKS=true; shift;; *) echo "unknown option $1" >&2; exit 64;; esac; done
[[ -n "$DOMAIN" ]] || { echo "--domain is required" >&2; exit 64; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-compose-json.sh disable=SC1091
source "$repo_root/scripts/test-server-compose-json.sh"
# shellcheck source=scripts/test-server-installer-lib.sh disable=SC1091
source "$repo_root/scripts/test-server-installer-lib.sh"
compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$ENV_FILE")
ok(){ printf 'PASS: %s\n' "$*"; }
not_run(){ printf 'NOT_RUN: %s\n' "$*"; }
fail(){ printf 'FAIL: %s\n' "$*" >&2; exit 1; }
if [[ ! -f "$RUNTIME_DIR/state.json" ]] || ! jq -e --arg d "$DOMAIN" '.environment=="TEST" and .root_domain==$d and .compose_project=="vpn-sale"' "$RUNTIME_DIR/state.json" >/dev/null; then fail "runtime state mismatch"; fi
ok "runtime state is TEST for $DOMAIN at commit $(jq -r '.selected_commit' "$RUNTIME_DIR/state.json")"

[[ $(stat -c %a "$RUNTIME_DIR") == 700 && $(stat -c %a "$ENV_FILE") == 600 && $(stat -c %a "$RUNTIME_DIR/state.json") == 600 ]] || fail "runtime permissions are not 0700/0600"; ok "runtime and state permissions are restrictive"
docker --version | redact >/dev/null; docker compose version | redact >/dev/null; ok "Docker Engine and Compose versions available"
for key in VPN_SALE_PROVIDER_WRITES_ENABLED VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED; do [[ "$(get_env "$key" "$ENV_FILE")" == false ]] || fail "$key must remain disabled"; done; ok "provider writes, fake payment success, and fake customer auth disabled"
manual_enabled="$(get_env VPN_SALE_MANUAL_CARD_TOPUPS_ENABLED "$ENV_FILE")"
[[ "$manual_enabled" == true || "$manual_enabled" == false ]] || fail "invalid manual top-up feature value"
if [[ "$manual_enabled" == true ]]; then
  worker_id="$(compose_service_container_id worker "${compose[@]}" 2>/dev/null || true)"
  [[ -n "$worker_id" && "$(docker_container_state "$worker_id")" == running ]] || fail "manual top-up outbox worker is not running"
  receipt_mode="$("${compose[@]}" exec -T api stat -c %a /var/lib/vpnsale/private/manual-topups | tr -d '\r\n')"
  [[ "$receipt_mode" == 700 ]] || fail "receipt directory permissions are not 0700"
fi
! rg -i 'card(_|-)?(number|destination)|iban|account_destination' "$ENV_FILE" >/dev/null || fail "forbidden destination configuration present"
ok "manual top-up flag, worker, private evidence, and no-destination configuration verified"
for svc in api customer-web admin-web reseller-web postgres redis; do [[ "$(compose_service_field "$svc" RestartCount "${compose[@]}" 2>/dev/null || printf 0)" == 0 ]] || fail "$svc has restarted"; done; ok "zero service restart loops"
"$repo_root/scripts/verify-test-server-compose.sh" "$ENV_FILE" >/dev/null; ok "Compose config renders with expected services/profiles"
for svc in postgres redis; do [[ "$(compose_service_field "$svc" Health "${compose[@]}")" == healthy ]] || fail "$svc not healthy"; ok "$svc healthy"; done
pg_user="$(get_env POSTGRES_USER "$ENV_FILE")"; pg_db="$(get_env POSTGRES_DB "$ENV_FILE")"
"${compose[@]}" exec -T postgres pg_isready -U "$pg_user" -d "$pg_db" >/dev/null || fail "PostgreSQL readiness failed for configured role/database"; ok "PostgreSQL accepts configured user/database"
"${compose[@]}" run --rm --no-deps api alembic -c /app/apps/api/alembic.ini current | grep -Fq "(head)"; ok "Alembic is at expected head as non-root API user"
for url in http://127.0.0.1:8000/health http://127.0.0.1:8000/ready http://127.0.0.1:8000/version http://127.0.0.1:3000 http://127.0.0.1:3001 http://127.0.0.1:3002; do curl -fsS --max-time 10 "$url" >/dev/null || fail "local HTTP failed: $url"; ok "local HTTP $url"; done
systemctl is-active --quiet caddy || fail "caddy inactive"; caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile >/dev/null; is_managed_caddyfile /etc/caddy/Caddyfile || fail "Caddyfile is not installer-managed"; ! grep -Fq 'fast.dr-ping.com' /etc/caddy/Caddyfile || fail "forbidden fast.dr-ping.com in Caddyfile"; ok "managed Caddy active and validates"
for p in 80 443; do ss -ltnp "sport = :$p" | grep -Fq caddy || fail "port $p not owned by managed Caddy"; ok "port $p owned by Caddy"; done
for bind in '127.0.0.1:8000' '127.0.0.1:3000' '127.0.0.1:3001' '127.0.0.1:3002'; do ss -ltn | grep -Fq "$bind" || fail "missing loopback binding $bind"; ok "$bind loopback-bound"; done
"${compose[@]}" config --format json | jq -e '(.services.postgres.ports // []) == [] and (.services.redis.ports // []) == [] and (.services.worker.ports // []) == [] and (.services["telegram-bot"].ports // []) == []' >/dev/null || fail "private services publish ports"; ok "PostgreSQL/Redis/worker/Telegram publish no ports"
if [[ "$NETWORK_CHECKS" == true ]]; then for u in "https://app.$DOMAIN" "https://api.$DOMAIN/health" "https://admin.$DOMAIN" "https://reseller.$DOMAIN"; do curl -fsS --max-time 20 "$u" >/dev/null || fail "HTTPS smoke failed: $u"; ok "HTTPS $u"; done; else not_run "public DNS, HTTPS, and certificate checks (enable with --network-checks)"; fi
bot_enabled="$(get_env VPN_SALE_BOT_ENABLED "$ENV_FILE")"
bot_mode="$(get_env VPN_SALE_BOT_MODE "$ENV_FILE")"
bot_username="$(get_env VPN_SALE_TELEGRAM_BOT_USERNAME "$ENV_FILE")"
if [[ -n "$bot_username" && "$bot_username" != "disabled_bot" ]]; then
  if ! "${compose[@]}" exec -T customer-web grep -R -F -- "$bot_username" .next/static .next/server >/dev/null; then
    fail "customer-web production bundle does not contain configured Telegram bot username: $bot_username"
  fi
  ok "customer-web production bundle contains configured Telegram bot username"
fi
if [[ "$bot_enabled" == true ]]; then
  bot_container_id="$(compose_service_container_id telegram-bot "${compose[@]}" 2>/dev/null || true)"
  [[ -n "$bot_container_id" ]] || fail "telegram bot container missing or not unique while VPN_SALE_BOT_ENABLED=true"
  bot_state="$(docker_container_state "$bot_container_id" 2>/dev/null || true)"
  [[ -n "$bot_state" ]] || fail "telegram bot container state unavailable while VPN_SALE_BOT_ENABLED=true"
  [[ "$bot_state" == running ]] || fail "telegram bot must be running when enabled; redacted state=$bot_state mode=${bot_mode:-unset}"
  [[ "$bot_mode" == polling ]] || fail "telegram bot must use polling mode on the TEST server when enabled; redacted mode=${bot_mode:-unset}"
  started_at="$(docker_container_started_at "$bot_container_id" 2>/dev/null || true)"
  [[ -n "$started_at" ]] || fail "telegram bot has no valid start time"
  # shellcheck disable=SC2016
  bot_env="$("${compose[@]}" exec -T telegram-bot sh -c 'printf "VPN_SALE_BOT_ENABLED=%s\nVPN_SALE_BOT_MODE=%s\n" "$VPN_SALE_BOT_ENABLED" "$VPN_SALE_BOT_MODE"')"
  expected_bot_env=$'VPN_SALE_BOT_ENABLED=true\nVPN_SALE_BOT_MODE=polling'
  [[ "$bot_env" == "$expected_bot_env" ]] || fail "telegram bot container has unexpected redacted runtime environment"
  restart_count="$(docker_container_restart_count "$bot_container_id" 2>/dev/null || true)"
  [[ "$restart_count" == 0 ]] || fail "telegram bot container is restarting"
  token="$(get_env VPN_SALE_TELEGRAM_BOT_TOKEN "$ENV_FILE")"
  app_url="$(get_env VPN_SALE_PUBLIC_APP_ORIGIN "$ENV_FILE")"
  telegram_api "$token" getMe | jq -e '.ok == true' >/dev/null || fail "Telegram getMe failed"
  telegram_api "$token" getWebhookInfo | jq -e '.ok == true and .result.url == ""' >/dev/null || fail "Telegram webhook is not empty"
  menu_json="$(telegram_api "$token" getChatMenuButton)" || fail "Telegram menu query failed"
  [[ "$(jq -r '.ok' <<<"$menu_json")" == true && "$(jq -r '.result.type // empty' <<<"$menu_json")" == web_app ]] || fail "Telegram default menu is not web_app"
  https_url_equal "$app_url" "$(jq -r '.result.web_app.url // empty' <<<"$menu_json")" || fail "Telegram default menu URL does not match public app origin"
  bot_logs=""
  for _ in 1 2 3 4 5; do
    bot_logs="$("${compose[@]}" logs --no-color --tail=120 telegram-bot 2>/dev/null | sed -E 's/(token|secret|password|database_url|postgresql:\/\/)[^[:space:]]+/REDACTED/Ig')"
    printf '%s\n' "$bot_logs" | rg -F 'telegram bot polling initialization successful' >/dev/null && break
    sleep 2
  done
  ! printf '%s\n' "$bot_logs" | rg -i 'disabled runtime|bot_token|BEGIN ENV|POSTGRES_PASSWORD|DATABASE_URL|postgresql://' >/dev/null || fail "telegram bot recent safe logs contain disabled runtime or secret-shaped output"
  printf '%s\n' "$bot_logs" | rg -F 'telegram bot polling initialization successful' >/dev/null || fail "telegram bot startup did not report successful polling initialization"
  "${compose[@]}" exec -T telegram-bot python - <<'PYBOTV2' | rg -Fx 'vpn-sale-telegram-bot-v2-foundation' >/dev/null || fail "telegram bot image missing Bot V2 version marker"
from telegram_bot.version import BOT_V2_VERSION_MARKER
print(BOT_V2_VERSION_MARKER)
PYBOTV2
  ok "Telegram bot running with redacted runtime enabled=true mode=polling, no restarts, safe logs, and Bot V2 marker"
elif [[ "$bot_enabled" == false || -z "$bot_enabled" ]]; then
  ok "Telegram bot disabled by runtime configuration"
else
  fail "invalid VPN_SALE_BOT_ENABLED value in runtime env"
fi
systemctl is-active --quiet fail2ban || fail "fail2ban inactive"; ok "fail2ban active"
swapon --show --noheadings | grep -q . || fail "swap missing"; ok "swap present"
! rg -n 'fast\.dr-ping\.com' "$RUNTIME_DIR" /etc/caddy/Caddyfile >/dev/null || fail "fast.dr-ping.com present in generated deployment configuration"; ok "fast.dr-ping.com absent from generated deployment configuration"
printf 'Verification completed without exposing secrets.\n'
