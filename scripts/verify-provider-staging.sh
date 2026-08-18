#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${VPN_SALE_STAGING_ENV_FILE:-/opt/vpn-sale-runtime/staging.env}"

usage() {
  cat <<'USAGE'
Usage: VPN_SALE_STAGING_CONFIRM=disposable-provider-write-smoke \
       bash scripts/verify-provider-staging.sh [--env-file FILE]

This command is staging-only. It refuses CI, production/test environments, fake auth/payment,
and provider-writes-off configurations. It never performs a provider mutation itself.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      env_file="${2:?--env-file requires a path}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      exit 64
      ;;
  esac
done

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

ok() {
  printf 'PASS: %s\n' "$*"
}

get_env() {
  local key="$1"
  local file="$2"
  awk -F= -v wanted="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == wanted {
      value=substr($0, index($0, "=")+1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if ((substr(value,1,1)=="\"" && substr(value,length(value),1)=="\"") ||
          (substr(value,1,1)=="\047" && substr(value,length(value),1)=="\047")) {
        value=substr(value,2,length(value)-2)
      }
      print value
      exit
    }
  ' "$file"
}

[[ "${CI:-false}" != true && "${GITHUB_ACTIONS:-false}" != true ]] || fail "provider staging verification refuses CI"
[[ "${VPN_SALE_STAGING_CONFIRM:-}" == "disposable-provider-write-smoke" ]] || fail "explicit disposable staging confirmation is required"
[[ -f "$env_file" ]] || fail "staging env file not found"
mode="$(stat -c %a "$env_file")"
[[ "$mode" == 600 || "$mode" == 400 ]] || fail "staging env file must be mode 0600 or 0400"
ok "staging env file permissions are restrictive"

[[ "$(get_env VPN_SALE_ENVIRONMENT "$env_file")" == staging ]] || fail "VPN_SALE_ENVIRONMENT must be staging"
[[ "$(get_env VPN_SALE_PROVIDER_WRITES_ENABLED "$env_file")" == true ]] || fail "provider writes must be explicitly enabled for disposable staging"
[[ "$(get_env VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED "$env_file")" == false ]] || fail "fake customer auth must remain disabled"
[[ "$(get_env VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED "$env_file")" == false ]] || fail "fake payment success must remain disabled"
[[ "$(get_env VPN_SALE_BOT_ENABLED "$env_file")" == true ]] || fail "Telegram bot must be enabled"
[[ "$(get_env VPN_SALE_BOT_MODE "$env_file")" == polling ]] || fail "Telegram bot must use polling"
[[ -n "$(get_env VPN_SALE_TELEGRAM_BOT_TOKEN "$env_file")" ]] || fail "Telegram bot token is missing"
[[ -n "$(get_env PROVIDER_VAULT_MASTER_KEY_B64 "$env_file")" ]] || fail "provider vault key is missing"
ok "staging-only environment gates are valid"

compose=("$repo_root/scripts/vpn-sale-compose-staging" --env-file "$env_file")
"${compose[@]}" --profile ops --profile telegram config --format json | python -c '
import json, sys
cfg=json.load(sys.stdin)
services=cfg.get("services", {})
for name in ("postgres", "redis", "worker", "telegram-bot"):
    if services.get(name, {}).get("ports"):
        raise SystemExit(f"private service publishes ports: {name}")
worker=services.get("worker", {}).get("environment", {})
api=services.get("api", {}).get("environment", {})
bot=services.get("telegram-bot", {}).get("environment", {})
if str(worker.get("VPN_SALE_PROVIDER_WRITES_ENABLED", "")).lower() != "true":
    raise SystemExit("worker provider writes are not enabled")
if str(api.get("VPN_SALE_PROVIDER_WRITES_ENABLED", "")).lower() != "false":
    raise SystemExit("API must not receive provider-write authority")
if str(api.get("VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED", "")).lower() != "false":
    raise SystemExit("fake customer auth enabled")
if str(api.get("VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED", "")).lower() != "false":
    raise SystemExit("fake payment enabled")
if str(bot.get("VPN_SALE_BOT_MODE", "")).lower() != "polling":
    raise SystemExit("Telegram bot is not polling")
'
ok "Compose keeps provider-write authority on the worker and private services unexposed"

for service in postgres redis api worker telegram-bot; do
  if ! "${compose[@]}" --profile ops --profile telegram ps --status running --services | grep -Fxq "$service"; then
    fail "$service is not running"
  fi
done
ok "staging database, Redis, API, worker and Telegram bot are running"

"${compose[@]}" --profile ops --profile telegram run --rm --no-deps api \
  alembic -c /app/apps/api/alembic.ini current | grep -Fq '(head)' || fail "Alembic is not at head"
ok "database migrations are at head"

curl -fsS --max-time 10 http://127.0.0.1:8000/health >/dev/null || fail "API health failed"
ok "API health is reachable only on loopback"

"${compose[@]}" --profile ops --profile telegram exec -T worker \
  python -m platform_worker.staging_preflight >/dev/null || fail "provider staging preflight failed"
ok "certified Sanaei target, binding, credential and contract metadata are ready"

bot_logs="$("${compose[@]}" --profile ops --profile telegram logs --no-color --tail=120 telegram-bot 2>/dev/null || true)"
printf '%s\n' "$bot_logs" | grep -Fq 'telegram bot polling initialization successful' || fail "Telegram polling initialization is not confirmed"
if printf '%s\n' "$bot_logs" | grep -Eqi 'bot_token|BEGIN ENV|POSTGRES_PASSWORD|DATABASE_URL|postgresql://'; then
  fail "Telegram recent logs contain forbidden secret-shaped output"
fi
ok "Telegram polling initialized with safe recent logs"

worker_logs="$("${compose[@]}" --profile ops --profile telegram logs --no-color --tail=120 worker 2>/dev/null || true)"
if printf '%s\n' "$worker_logs" | grep -Eqi 'PROVIDER_VAULT_MASTER_KEY_B64|password=|DATABASE_URL|postgresql://'; then
  fail "worker recent logs contain forbidden secret-shaped output"
fi
ok "worker recent logs contain no forbidden secret-shaped output"

printf 'Provider staging harness verification passed. Real disposable end-to-end provider smoke is still a separate operator action.\n'
