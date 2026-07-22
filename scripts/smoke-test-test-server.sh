#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${VPN_SALE_TEST_SERVER_ENV_FILE:-/opt/vpn-sale-runtime/test.env}"
domain="${VPN_SALE_TEST_SERVER_DOMAIN:-}"
compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$env_file")
# shellcheck source=scripts/test-server-compose-json.sh disable=SC1091
source "$repo_root/scripts/test-server-compose-json.sh"
telegram_api(){ local token="$1" method="$2"; shift 2; printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$token" "$method" | curl -fsS --config - "$@"; }
redact(){ sed -E 's/(bot[0-9]+:)?[A-Za-z0-9_-]{24,}/<redacted>/g; s/(TOKEN|PASSWORD|SECRET|KEY)=([^[:space:]]+)/\1=<redacted>/g'; }
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
get_env(){ awk -F= -v k="$1" '$1==k {sub(/^[^=]*=/,""); print; exit}' "$env_file"; }
compose_ps_json_array "${compose[@]}" | jq -e 'all(.RestartCount == 0)' >/dev/null
for svc in postgres redis; do compose_service_field "$svc" Health "${compose[@]}" | jq -Re '. == "healthy"' >/dev/null; done
"${compose[@]}" config --format json | jq -e '.services.worker == null or (.services.worker.profiles // [] | index("ops"))' >/dev/null
"${compose[@]}" config --format json | jq -e '(.services.postgres.ports // []) == [] and (.services.redis.ports // []) == []' >/dev/null
curl -fsS http://127.0.0.1:8000/health >/dev/null
curl -fsS http://127.0.0.1:8000/ready >/dev/null
for port in 3000 3001 3002; do curl -fsS "http://127.0.0.1:$port" >/dev/null; done
if ss -ltn | awk '$4 ~ /:(5432|6379)$/ && $4 !~ /^127\.0\.0\.1:/ {bad=1} END{exit bad?0:1}'; then echo 'database/redis port is public or bound on host' >&2; exit 1; fi
"${compose[@]}" run --rm --no-deps api alembic -c apps/api/alembic.ini current | tee /tmp/vpn-sale-alembic-current.txt | grep -q '(head)'
bot_username="$(get_env VPN_SALE_TELEGRAM_BOT_USERNAME)"
if [[ -n "$bot_username" && "$bot_username" != "disabled_bot" ]]; then
  "${compose[@]}" exec -T customer-web sh -lc "grep -R \"$bot_username\" .next/static .next/server >/dev/null"
fi
if [[ -n "$domain" ]]; then
  for url in "https://app.$domain" "https://api.$domain/health" "https://admin.$domain" "https://reseller.$domain"; do curl -fsSI --connect-timeout 5 "$url" >/dev/null; echo | openssl s_client -servername "$(awk -F/ '{print $3}' <<<"$url")" -connect "$(awk -F/ '{print $3}' <<<"$url")":443 2>/dev/null | openssl x509 -noout -subject >/dev/null; done
fi
if systemctl is-active --quiet caddy; then caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile; check_caddyfile /etc/caddy/Caddyfile; fi
if grep -q '^VPN_SALE_BOT_ENABLED=true' "$env_file"; then
  token="$(get_env VPN_SALE_TELEGRAM_BOT_TOKEN)"; app_url="$(get_env VPN_SALE_PUBLIC_APP_ORIGIN)"
  compose_service_json_array telegram-bot "${compose[@]}" | jq -e --arg service telegram-bot 'map(select(.Service == $service)) | first | (.RestartCount == 0 and .State == "running")' >/dev/null
  telegram_api "$token" getMe | jq -e '.ok == true' >/dev/null
  telegram_api "$token" getChatMenuButton | jq -e --arg u "$app_url" '.ok == true and .result.web_app.url == $u' >/dev/null
  telegram_api "$token" getWebhookInfo | jq -e '.ok == true and (.result.url == "")' >/dev/null
fi
"${compose[@]}" logs --no-color --tail=200 2>&1 | redact >/tmp/vpn-sale-smoke-redacted.log
if [[ -n "$(get_env POSTGRES_PASSWORD)" ]] && grep -F "$(get_env POSTGRES_PASSWORD)" /tmp/vpn-sale-smoke-redacted.log >/dev/null; then echo 'secret appeared in smoke report' >&2; exit 1; fi
printf 'test-server smoke checks passed\n'
