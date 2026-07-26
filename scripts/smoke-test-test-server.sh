#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${VPN_SALE_TEST_SERVER_ENV_FILE:-/opt/vpn-sale-runtime/test.env}"
domain="${VPN_SALE_TEST_SERVER_DOMAIN:-}"
compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$env_file")
# shellcheck source=scripts/test-server-compose-json.sh disable=SC1091
source "$repo_root/scripts/test-server-compose-json.sh"
telegram_api(){ local token="$1" method="$2"; shift 2; printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$token" "$method" | curl -fsS --config - "$@"; }
redact(){
  sed -E \
    -e 's/((DATABASE_URL|PASSWORD|TOKEN|COOKIE|SECRET|KEY)=)[^[:space:]]+/\1<redacted>/Ig' \
    -e 's#((https?|postgresql(\+asyncpg)?|redis)://)[^/@[:space:]]+:[^/@[:space:]]+@#\1<redacted>@#Ig' \
    -e 's/(bot)?[0-9]{6,}:[A-Za-z0-9_-]{20,}/<redacted>/g'
}
check_public_https(){
  local label="$1" url="$2" curl_error
  if ! curl_error="$(curl --fail --silent --show-error --output /dev/null --connect-timeout 5 --max-time 20 "$url" 2>&1)"; then
    printf 'ERROR: %s public HTTPS GET failed: %s\n' "$label" "$curl_error" | redact >&2
    return 1
  fi
}
check_caddyfile(){
  local caddyfile="$1"
  if grep -Fq 'email off' "$caddyfile"; then
    echo "ERROR: invalid Caddy email off directive detected" >&2
    exit 1
  fi
}
if [[ "${1:-}" == "--check-caddyfile" ]]; then
  check_caddyfile "${2:?caddyfile path is required}"
  printf '%s\n' 'Caddyfile email directive check passed'
  exit 0
fi
if [[ "${1:-}" == "--check-public-url" ]]; then
  check_public_https "${2:?endpoint label is required}" "${3:?endpoint URL is required}"
  exit 0
fi
if [[ "${1:-}" == "--check-redaction" ]]; then
  redact
  exit 0
fi
get_env(){ awk -F= -v k="$1" '$1==k {sub(/^[^=]*=/,""); print; exit}' "$env_file"; }
for svc in api customer-web admin-web reseller-web postgres redis; do
  assert_compose_service_not_restarted "$svc" "${compose[@]}"
done
for svc in postgres redis; do compose_service_field "$svc" Health "${compose[@]}" | jq -Re '. == "healthy"' >/dev/null; done
"${compose[@]}" config --format json | jq -e '.services.worker == null or (.services.worker.profiles // [] | index("ops"))' >/dev/null
"${compose[@]}" config --format json | jq -e '(.services.postgres.ports // []) == [] and (.services.redis.ports // []) == []' >/dev/null
curl -fsS http://127.0.0.1:8000/health >/dev/null
curl -fsS http://127.0.0.1:8000/ready >/dev/null
for port in 3000 3001 3002; do curl -fsS "http://127.0.0.1:$port" >/dev/null; done
if ss -ltn | awk '$4 ~ /:(5432|6379)$/ && $4 !~ /^127\.0\.0\.1:/ {bad=1} END{exit bad?0:1}'; then echo 'database/redis port is public or bound on host' >&2; exit 1; fi
"${compose[@]}" run --rm --no-deps api alembic -c /app/apps/api/alembic.ini current | tee /tmp/vpn-sale-alembic-current.txt | grep -q '(head)'
bot_username="$(get_env VPN_SALE_TELEGRAM_BOT_USERNAME)"
if [[ -n "$bot_username" && "$bot_username" != "disabled_bot" ]]; then
  "${compose[@]}" exec -T customer-web sh -lc "grep -R \"$bot_username\" .next/static .next/server >/dev/null"
fi
if [[ -n "$domain" ]]; then
  while IFS='|' read -r label url; do
    check_public_https "$label" "$url"
    host="$(awk -F/ '{print $3}' <<<"$url")"
    echo | openssl s_client -servername "$host" -connect "$host":443 2>/dev/null | openssl x509 -noout -subject >/dev/null
  done <<EOF
Customer web|https://app.$domain
API health|https://api.$domain/health
Admin web|https://admin.$domain
Reseller web|https://reseller.$domain
EOF
fi
if systemctl is-active --quiet caddy; then caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile; check_caddyfile /etc/caddy/Caddyfile; fi
if grep -q '^VPN_SALE_BOT_ENABLED=true' "$env_file"; then
  token="$(get_env VPN_SALE_TELEGRAM_BOT_TOKEN)"; app_url="$(get_env VPN_SALE_PUBLIC_APP_ORIGIN)"
  bot_state="$(compose_service_field telegram-bot State "${compose[@]}" 2>/dev/null || printf missing)"
  [[ "$bot_state" == running ]] || { echo "telegram bot enabled but not steadily running; redacted state=$bot_state" >&2; exit 1; }
  assert_compose_service_not_restarted telegram-bot "${compose[@]}"
  telegram_api "$token" getMe | jq -e '.ok == true' >/dev/null
  telegram_api "$token" getChatMenuButton | jq -e --arg u "$app_url" '.ok == true and .result.web_app.url == $u' >/dev/null
  telegram_api "$token" getWebhookInfo | jq -e '.ok == true and (.result.url == "")' >/dev/null
fi
"${compose[@]}" logs --no-color --tail=200 2>&1 | redact >/tmp/vpn-sale-smoke-redacted.log
if [[ -n "$(get_env POSTGRES_PASSWORD)" ]] && grep -F "$(get_env POSTGRES_PASSWORD)" /tmp/vpn-sale-smoke-redacted.log >/dev/null; then echo 'secret appeared in smoke report' >&2; exit 1; fi
printf 'test-server smoke checks passed\n'
