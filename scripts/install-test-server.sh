#!/usr/bin/env bash
set -euo pipefail
phase="initialization"
fail(){ printf 'ERROR during %s: %s\n' "$phase" "$*" >&2; printf 'Safe diagnostics (secrets redacted): docker compose ps; journalctl -u caddy --no-pager -n 80; docker compose logs api --tail=80 | sed -E "s/(TOKEN|PASSWORD|SECRET|KEY)=([^[:space:]]+)/\\1=<redacted>/g"\n' >&2; exit 1; }
trap 'fail "command failed on line $LINENO"' ERR
DOMAIN=""; REPO="https://github.com/hmidrx/VPN-SALE.git"; REF="main"; RUNTIME_DIR="/opt/vpn-sale-runtime"; INSTALL_DIR="/opt/vpn-sale"
ENABLE_TELEGRAM=false; RESET_PG=false; SKIP_DNS=false; NON_INTERACTIVE=false; OVERRIDE_OS=false; TELEGRAM_BOT_TOKEN_FILE=""; TELEGRAM_BOT_USERNAME=""
while [[ $# -gt 0 ]]; do case "$1" in --domain) DOMAIN="${2:?}"; shift 2;; --repo) REPO="${2:?}"; shift 2;; --ref) REF="${2:?}"; shift 2;; --runtime-dir) RUNTIME_DIR="${2:?}"; shift 2;; --enable-telegram) ENABLE_TELEGRAM=true; shift;; --telegram-bot-token-file) TELEGRAM_BOT_TOKEN_FILE="${2:?}"; shift 2;; --telegram-bot-username) TELEGRAM_BOT_USERNAME="${2:?}"; shift 2;; --reset-disposable-postgres) RESET_PG=true; shift;; --skip-dns-wait) SKIP_DNS=true; shift;; --non-interactive) NON_INTERACTIVE=true; shift;; --allow-unsupported-os) OVERRIDE_OS=true; shift;; *) fail "unknown option $1";; esac; done
[[ $(id -u) -eq 0 ]] || fail "must run as root"
[[ -n "$DOMAIN" ]] || fail "--domain is required; no implicit production domain is used"
[[ "$DOMAIN" != "fast.dr-ping.com" && "$DOMAIN" != *".fast.dr-ping.com" ]] || fail "refusing unrelated hostname fast.dr-ping.com"
redact(){ sed -E 's/(TOKEN|PASSWORD|SECRET|KEY)=([^[:space:]]+)/\1=<redacted>/g'; }
gen(){ python3 -c 'import secrets; print(secrets.token_urlsafe(48))'; }
urlencode(){ RAW_VALUE="$1" python3 - <<'PY'
import os, urllib.parse
print(urllib.parse.quote(os.environ["RAW_VALUE"], safe=""))
PY
}
get_env(){ local key="$1" file="$2"; if [[ -f "$file" ]]; then awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/,""); print; exit}' "$file"; fi; }
set_kv(){ local file="$1" key="$2" value="$3"; if grep -q "^${key}=" "$file" 2>/dev/null; then python3 - "$file" "$key" "$value" <<'PY'
import pathlib, sys
path,key,value=pathlib.Path(sys.argv[1]),sys.argv[2],sys.argv[3]
lines=path.read_text().splitlines()
path.write_text("\n".join(f"{key}={value}" if line.startswith(f"{key}=") else line for line in lines)+"\n")
PY
else printf '%s=%s\n' "$key" "$value" >>"$file"; fi; }
telegram_api(){ local method="$1"; shift; printf 'url = "https://api.telegram.org/bot%s/%s"\n' "$BOT_TOKEN" "$method" | curl -fsS --retry 2 --connect-timeout 5 --config - "$@"; }
phase="preflight"
# /etc/os-release is provided by the base OS on supported Ubuntu servers.
# shellcheck source=/etc/os-release disable=SC1091
source /etc/os-release
[[ "${VERSION_ID:-}" == "24.04" || "$OVERRIDE_OS" == true ]] || fail "Ubuntu 24.04 required (or --allow-unsupported-os)"
(( $(nproc) >= 2 )) || fail "at least 2 CPU cores required"
(( $(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo) >= 1900 )) || fail "at least 2 GiB RAM required"
(( $(df -Pm / | awk 'NR==2{print $4}') >= 12000 )) || fail "at least 12 GiB free disk required"
is_installer_managed_caddy(){ [[ -f /etc/caddy/Caddyfile ]] && grep -Fq "# vpn-sale-test-server-managed" /etc/caddy/Caddyfile; }
for p in 80 443; do
  if ss -ltn "sport = :$p" | awk 'NR>1{exit 1}'; then
    continue
  fi
  if systemctl is-active --quiet caddy 2>/dev/null && is_installer_managed_caddy; then
    continue
  fi
  fail "port $p is already in use by an unmanaged process"
done
CUSTOMER_ORIGIN="https://app.$DOMAIN"; API_ORIGIN="https://api.$DOMAIN"; ADMIN_ORIGIN="https://admin.$DOMAIN"; RESELLER_ORIGIN="https://reseller.$DOMAIN"
if [[ "$SKIP_DNS" != true ]]; then for h in "app.$DOMAIN" "api.$DOMAIN" "admin.$DOMAIN" "reseller.$DOMAIN"; do getent ahosts "$h" >/dev/null || fail "DNS missing for $h"; done; fi
phase="install packages"
apt-get update
apt-get install -y git curl jq ca-certificates gnupg openssl python3 fail2ban debian-keyring debian-archive-keyring apt-transport-https ripgrep nodejs npm
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc; chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "${VERSION_CODENAME}" >/etc/apt/sources.list.d/docker.list
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /etc/apt/keyrings/caddy-stable-archive-keyring.gpg.tmp; mv /etc/apt/keyrings/caddy-stable-archive-keyring.gpg.tmp /etc/apt/keyrings/caddy-stable-archive-keyring.gpg
printf 'deb [signed-by=/etc/apt/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main\n' >/etc/apt/sources.list.d/caddy-stable.list
apt-get update; apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin caddy
systemctl enable --now docker fail2ban caddy
phase="swap"
if [[ $(swapon --show --noheadings | wc -l) -eq 0 ]]; then [[ -f /swapfile ]] || fallocate -l 4G /swapfile; chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon /swapfile; grep -qE '^/swapfile[[:space:]]' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab; fi
phase="checkout"
if [[ -d "$INSTALL_DIR/.git" ]]; then git -C "$INSTALL_DIR" diff --quiet || fail "tracked worktree is dirty"; git -C "$INSTALL_DIR" fetch origin "$REF" --prune; git -C "$INSTALL_DIR" checkout "$REF"; git -C "$INSTALL_DIR" merge --ff-only "origin/$REF"; else git clone --branch "$REF" "$REPO" "$INSTALL_DIR"; fi
printf 'Deploying commit: %s\n' "$(git -C "$INSTALL_DIR" rev-parse HEAD)"
cd "$INSTALL_DIR"
# shellcheck source=scripts/test-server-compose-json.sh
source ./scripts/test-server-compose-json.sh
phase="runtime env"
install -d -m 0700 "$RUNTIME_DIR"; ENV_FILE="$RUNTIME_DIR/test.env"; touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
if [[ "$RESET_PG" == true ]]; then printf 'WARNING: resetting disposable PostgreSQL volume only because --reset-disposable-postgres was passed\n' >&2; if ./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" ps postgres >/dev/null 2>&1; then ./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" stop postgres; fi; if docker volume inspect vpn-sale_test_server_postgres_data >/dev/null 2>&1; then docker volume rm vpn-sale_test_server_postgres_data; fi; fi
BOT_TOKEN=""
if [[ -n "$TELEGRAM_BOT_TOKEN_FILE" ]]; then
  [[ -r "$TELEGRAM_BOT_TOKEN_FILE" ]] || fail "telegram token file is not readable"
  token_mode="$(stat -c %a "$TELEGRAM_BOT_TOKEN_FILE")"
  [[ "$token_mode" == "600" ]] || fail "telegram token file must have mode 0600"
  BOT_TOKEN="$(tr -d '\r\n' <"$TELEGRAM_BOT_TOKEN_FILE")"
fi
if [[ "$ENABLE_TELEGRAM" == true && -z "$BOT_TOKEN" && "$NON_INTERACTIVE" == false ]]; then read -r -s -p 'Telegram bot token: ' BOT_TOKEN </dev/tty; printf '\n' >/dev/tty; fi
[[ "$ENABLE_TELEGRAM" == false || -n "$BOT_TOKEN" ]] || fail "telegram token required via --telegram-bot-token-file or hidden prompt"
if [[ "$ENABLE_TELEGRAM" == true ]]; then
  me_json="$(telegram_api getMe)"; [[ "$(jq -r '.ok' <<<"$me_json")" == true ]] || fail "Telegram getMe failed"
  derived_username="$(jq -r '.result.username // empty' <<<"$me_json")"; [[ -n "$derived_username" ]] || fail "Telegram getMe returned no username"
  if [[ -n "$TELEGRAM_BOT_USERNAME" && "$TELEGRAM_BOT_USERNAME" != "$derived_username" ]]; then fail "provided Telegram username does not match getMe"; fi
  TELEGRAM_BOT_USERNAME="$derived_username"
elif [[ -z "$TELEGRAM_BOT_USERNAME" ]]; then TELEGRAM_BOT_USERNAME="disabled_bot"; fi
cp -p "$ENV_FILE" "$ENV_FILE.bak.$(date -u +%Y%m%dT%H%M%SZ)"
PG_PASS="$(get_env POSTGRES_PASSWORD "$ENV_FILE")"; [[ -n "$PG_PASS" ]] || PG_PASS="${POSTGRES_PASSWORD:-$(gen)}"
DB_URL="postgresql+asyncpg://vpnsale_test:$(urlencode "$PG_PASS")@postgres:5432/vpnsale_test"
set_kv "$ENV_FILE" VPN_SALE_ENVIRONMENT TEST; set_kv "$ENV_FILE" POSTGRES_USER vpnsale_test; set_kv "$ENV_FILE" POSTGRES_DB vpnsale_test; set_kv "$ENV_FILE" POSTGRES_PASSWORD "$PG_PASS"; set_kv "$ENV_FILE" VPN_SALE_DATABASE_URL "$DB_URL"; set_kv "$ENV_FILE" DATABASE_URL "$DB_URL"; set_kv "$ENV_FILE" VPN_SALE_REDIS_URL redis://redis:6379/0
for k in VPN_SALE_IDENTITY_ENCRYPTION_KEY VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY VPN_SALE_ADMIN_CSRF_SECRET VPN_SALE_CUSTOMER_CSRF_SECRET VPN_SALE_TELEGRAM_RATE_LIMIT_KEY; do [[ -n "$(get_env "$k" "$ENV_FILE")" ]] || set_kv "$ENV_FILE" "$k" "$(gen)"; done
set_kv "$ENV_FILE" VPN_SALE_IDENTITY_ENCRYPTION_KEY_VERSION test-v1; set_kv "$ENV_FILE" VPN_SALE_API_PUBLIC_ORIGIN "$API_ORIGIN"; set_kv "$ENV_FILE" VPN_SALE_PUBLIC_APP_ORIGIN "$CUSTOMER_ORIGIN"; set_kv "$ENV_FILE" VPN_SALE_CUSTOMER_API_FRONTEND_URL "$API_ORIGIN"; set_kv "$ENV_FILE" VPN_SALE_CORS_ALLOWED_ORIGINS "[\"$CUSTOMER_ORIGIN\",\"$ADMIN_ORIGIN\",\"$RESELLER_ORIGIN\"]"; set_kv "$ENV_FILE" VPN_SALE_CUSTOMER_APP_NAME "VPN-SALE Test"; set_kv "$ENV_FILE" VPN_SALE_TELEGRAM_BOT_USERNAME "$TELEGRAM_BOT_USERNAME"; set_kv "$ENV_FILE" VPN_SALE_TELEGRAM_BOT_TOKEN "$BOT_TOKEN"; set_kv "$ENV_FILE" VPN_SALE_BOT_ENABLED "$ENABLE_TELEGRAM"; set_kv "$ENV_FILE" VPN_SALE_BOT_MODE "$([[ "$ENABLE_TELEGRAM" == true ]] && echo polling || echo disabled)"; set_kv "$ENV_FILE" VPN_SALE_CUSTOMER_MINI_APP_URL "$CUSTOMER_ORIGIN"; set_kv "$ENV_FILE" VPN_SALE_CUSTOMER_MINI_APP_ALLOWED_HOSTS "app.$DOMAIN"; set_kv "$ENV_FILE" VPN_SALE_PROVIDER_WRITES_ENABLED false; set_kv "$ENV_FILE" VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED false; set_kv "$ENV_FILE" VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED false
chmod 600 "$ENV_FILE"
for k in POSTGRES_PASSWORD VPN_SALE_DATABASE_URL VPN_SALE_REDIS_URL VPN_SALE_API_PUBLIC_ORIGIN VPN_SALE_PUBLIC_APP_ORIGIN VPN_SALE_TELEGRAM_BOT_USERNAME; do [[ -n "$(get_env "$k" "$ENV_FILE")" ]] || fail "missing required config $k"; done
phase="compose render"
./scripts/verify-test-server-compose.sh "$ENV_FILE"
./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" config >/tmp/vpn-sale-compose.rendered.yml
! grep -Eq '0\.0\.0\.0:(5432|6379)|:(5432|6379):(5432|6379)' /tmp/vpn-sale-compose.rendered.yml || fail "PostgreSQL or Redis host binding detected"
phase="build images"
profiles=( ); [[ "$ENABLE_TELEGRAM" == true ]] && profiles=(--profile telegram)
./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" "${profiles[@]}" build api customer-web admin-web reseller-web telegram-bot
phase="database and redis"
./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" up -d postgres redis
for svc in postgres redis; do wait_compose_service_healthy "$svc" 120 ./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" || fail "$svc did not become healthy"; done
phase="migrations"
./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" run --rm --no-deps api alembic -c apps/api/alembic.ini upgrade head
phase="start services"
start_services=(api customer-web admin-web reseller-web); [[ "$ENABLE_TELEGRAM" == true ]] && start_services+=(telegram-bot)
./scripts/vpn-sale-compose-test-server --env-file "$ENV_FILE" "${profiles[@]}" up -d "${start_services[@]}"
phase="Caddy"
tmp_caddy="$(mktemp)"; cat >"$tmp_caddy" <<CADDY
# vpn-sale-test-server-managed
app.$DOMAIN { reverse_proxy 127.0.0.1:3000 }
api.$DOMAIN { reverse_proxy 127.0.0.1:8000 }
admin.$DOMAIN { reverse_proxy 127.0.0.1:3001 }
reseller.$DOMAIN { reverse_proxy 127.0.0.1:3002 }
CADDY
caddy validate --config "$tmp_caddy"; install -m 0644 "$tmp_caddy" /etc/caddy/Caddyfile.new; mv /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile; systemctl reload caddy || systemctl restart caddy
phase="Telegram setup"
if [[ "$ENABLE_TELEGRAM" == true ]]; then
  telegram_api deleteWebhook -d drop_pending_updates=true >/dev/null
  telegram_api setMyCommands -H 'Content-Type: application/json' -d '{"commands":[{"command":"start","description":"Start"},{"command":"menu","description":"Open menu"},{"command":"help","description":"Help"},{"command":"profile","description":"Profile"},{"command":"security","description":"Security"}]}' >/dev/null
  telegram_api setChatMenuButton -H 'Content-Type: application/json' -d "{\"menu_button\":{\"type\":\"web_app\",\"text\":\"Open app\",\"web_app\":{\"url\":\"$CUSTOMER_ORIGIN\"}}}" >/dev/null
  telegram_api getChatMenuButton | jq -e --arg u "$CUSTOMER_ORIGIN" '.ok == true and .result.web_app.url == $u' >/dev/null
fi
phase="readiness"
./scripts/wait-for-http.sh http://127.0.0.1:8000/health 60; ./scripts/wait-for-http.sh http://127.0.0.1:8000/ready 60
for p in 3000 3001 3002; do ./scripts/wait-for-http.sh "http://127.0.0.1:$p" 60; done
if [[ "$SKIP_DNS" != true ]]; then for u in "$CUSTOMER_ORIGIN" "$API_ORIGIN/health" "$ADMIN_ORIGIN" "$RESELLER_ORIGIN"; do ./scripts/wait-for-http.sh "$u" 120; done; fi
phase="smoke tests"
VPN_SALE_TEST_SERVER_ENV_FILE="$ENV_FILE" VPN_SALE_TEST_SERVER_DOMAIN="$DOMAIN" ./scripts/smoke-test-test-server.sh
printf 'Test server deployment completed for %s at commit %s\n' "$DOMAIN" "$(git rev-parse HEAD)"
