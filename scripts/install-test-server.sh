#!/usr/bin/env bash
set -euo pipefail
phase="initialization"
fail(){ printf 'ERROR during %s: %s\n' "$phase" "$*" >&2; printf 'Safe diagnostics are redacted. Run scripts/verify-test-server.sh for details after fixing the error.\n' >&2; exit 1; }
trap 'fail "command failed on line $LINENO"' ERR
DOMAIN=""; REPO="https://github.com/hmidrx/VPN-SALE.git"; REF="main"; EXPECTED_COMMIT=""; RUNTIME_DIR="/opt/vpn-sale-runtime"; INSTALL_DIR="/opt/vpn-sale"; PROJECT="vpn-sale"
ENABLE_TELEGRAM=false; RESET_PG=false; SKIP_DNS=false; NON_INTERACTIVE=false; OVERRIDE_OS=false; TELEGRAM_BOT_TOKEN_FILE=""; TELEGRAM_BOT_USERNAME=""
usage(){ cat <<USAGE
Usage: scripts/install-test-server.sh --domain DOMAIN [options]

Options:
  --domain DOMAIN                    Root test domain to deploy.
  --repo URL                         Git repository to clone (default: hmidrx/VPN-SALE).
  --ref REF                          Git ref to deploy (default: main).
  --expected-commit SHA              Require the bootstrap-resolved commit.
  --runtime-dir DIR                  Runtime state directory.
  --install-dir DIR                  Checkout directory.
  --enable-telegram                  Enable Telegram polling bot.
  --telegram-bot-token-file FILE     Mode-0600 Telegram token file.
  --telegram-bot-username USERNAME   Expected Telegram bot username.
  --reset-disposable-postgres        Reset only disposable TEST PostgreSQL resources.
  --skip-dns-wait                    Skip public DNS preflight/smoke waits.
  --non-interactive                  Do not prompt for secrets.
  --allow-unsupported-os             Bypass Ubuntu 24.04 guard.
  --help                             Show this help and exit.
USAGE
}
while [[ $# -gt 0 ]]; do case "$1" in --help) usage; exit 0;; --domain) DOMAIN="${2:?}"; shift 2;; --repo) REPO="${2:?}"; shift 2;; --ref) REF="${2:?}"; shift 2;; --expected-commit) EXPECTED_COMMIT="${2:?}"; shift 2;; --runtime-dir) RUNTIME_DIR="${2:?}"; shift 2;; --install-dir) INSTALL_DIR="${2:?}"; shift 2;; --enable-telegram) ENABLE_TELEGRAM=true; shift;; --telegram-bot-token-file) TELEGRAM_BOT_TOKEN_FILE="${2:?}"; shift 2;; --telegram-bot-username) TELEGRAM_BOT_USERNAME="${2:?}"; shift 2;; --reset-disposable-postgres) RESET_PG=true; shift;; --skip-dns-wait) SKIP_DNS=true; shift;; --non-interactive) NON_INTERACTIVE=true; shift;; --allow-unsupported-os) OVERRIDE_OS=true; shift;; *) fail "unknown option $1";; esac; done
[[ $(id -u) -eq 0 ]] || fail "must run as root"
[[ -n "$DOMAIN" ]] || fail "--domain is required; no implicit production domain is used"
[[ "$DOMAIN" != "fast.dr-ping.com" && "$DOMAIN" != *".fast.dr-ping.com" ]] || fail "refusing unrelated hostname fast.dr-ping.com"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -d "$repo_root/.git" && -f "$repo_root/scripts/test-server-installer-lib.sh" ]] || fail "installer must run from a complete Git checkout; use scripts/bootstrap-test-server.sh"
# shellcheck source=scripts/test-server-installer-lib.sh disable=SC1091
source "$repo_root/scripts/test-server-installer-lib.sh"
# shellcheck source=scripts/test-server-compose-json.sh disable=SC1091
source "$repo_root/scripts/test-server-compose-json.sh"
umask 077
# Database URLs are built with urlencode() semantics via urllib.parse.quote(os.environ["RAW_VALUE"], safe="") in test-server-installer-lib.sh.
STATE_FILE="$RUNTIME_DIR/state.json"; ENV_FILE="$RUNTIME_DIR/test.env"; SECRETS_DIR="$RUNTIME_DIR/secrets"; PG_PASSWORD_FILE="$SECRETS_DIR/postgres-password"; CADDY_MARKER="$RUNTIME_DIR/caddy-managed.sha256"
compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$ENV_FILE")
pg_volume="${PROJECT}_test_server_postgres_data"; pg_container="${PROJECT}-postgres-1"
volume_exists(){ docker volume inspect "$pg_volume" >/dev/null 2>&1; }
phase_done(){ write_state "$STATE_FILE" "$1" TEST "$DOMAIN" "$REPO" "$REF" "$(git -C "$INSTALL_DIR" rev-parse HEAD 2>/dev/null || printf unknown)" "$PROJECT"; }
stop_safe_caddy(){
  if systemctl is-active --quiet caddy 2>/dev/null; then
    if is_managed_caddyfile /etc/caddy/Caddyfile || is_default_caddyfile /etc/caddy/Caddyfile; then systemctl stop caddy; else return 1; fi
  fi
}
preflight_ports(){
  for p in 80 443; do
    if ss -ltn "sport = :$p" | awk 'NR>1{exit 1}'; then continue; fi
    if systemctl is-active --quiet caddy 2>/dev/null && (is_managed_caddyfile /etc/caddy/Caddyfile || is_default_caddyfile /etc/caddy/Caddyfile); then continue; fi
    fail "port $p is already in use by an unmanaged listener; installer will not stop unrelated processes"
  done
}
phase="preflight"
# shellcheck source=/etc/os-release disable=SC1091
source /etc/os-release
[[ "${VERSION_ID:-}" == "24.04" || "$OVERRIDE_OS" == true ]] || fail "Ubuntu 24.04 required (or --allow-unsupported-os)"
(( $(nproc) >= 2 )) || fail "at least 2 CPU cores required"
(( $(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo) >= 1900 )) || fail "at least 2 GiB RAM required"
(( $(df -Pm / | awk 'NR==2{print $4}') >= 12000 )) || fail "at least 12 GiB free disk required"
preflight_ports
for h in "app.$DOMAIN" "api.$DOMAIN" "admin.$DOMAIN" "reseller.$DOMAIN"; do [[ "$h" != fast.dr-ping.com ]]; done
if [[ "$SKIP_DNS" != true ]]; then for h in "app.$DOMAIN" "api.$DOMAIN" "admin.$DOMAIN" "reseller.$DOMAIN"; do getent ahosts "$h" >/dev/null || fail "DNS missing for $h"; done; fi
phase_done preflight
phase="install packages"
quarantine_broken_installer_caddy_source
apt-get update
apt-get install -y ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https
apt-get install -y git jq openssl python3 fail2ban ripgrep nodejs npm
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc; chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "${VERSION_CODENAME}" >/etc/apt/sources.list.d/docker.list
install_caddy_apt_repository
apt_get_update_with_caddy_retry; apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin caddy
stop_safe_caddy || fail "caddy.service is active with non-default unmanaged configuration"
systemctl enable --now docker fail2ban
phase_done packages
phase="swap"
if [[ $(swapon --show --noheadings | wc -l) -eq 0 ]]; then [[ -f /swapfile ]] || fallocate -l 4G /swapfile; chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon /swapfile; grep -qE '^/swapfile[[:space:]]' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab; fi
phase_done swap
phase="checkout"
[[ "$repo_root" == "$INSTALL_DIR" ]] || fail "installer checkout must equal --install-dir; use the standalone bootstrap"
git -C "$INSTALL_DIR" diff --quiet --ignore-submodules -- || fail "tracked worktree is dirty"
current_commit="$(git -C "$INSTALL_DIR" rev-parse HEAD)"
[[ -z "$EXPECTED_COMMIT" || "$current_commit" == "$EXPECTED_COMMIT" ]] || fail "checkout does not match bootstrap-selected commit"
printf 'Selected ref: %s\nDeploying commit: %s\n' "$REF" "$current_commit"
normalize_checkout_permissions "$INSTALL_DIR" || fail "checkout permission normalization failed"
cd "$INSTALL_DIR"; repo_root="$INSTALL_DIR"; compose=("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$ENV_FILE")
phase_done checkout
phase="runtime secrets"
install -d -m 0700 "$RUNTIME_DIR" "$SECRETS_DIR"
if [[ "$RESET_PG" == true ]]; then
  printf 'Resetting TEST PostgreSQL resources only: container=%s volume=%s\n' "$pg_container" "$pg_volume" >&2
  docker rm -f "$pg_container" >/dev/null 2>&1 || true
  docker volume rm "$pg_volume" >/dev/null 2>&1 || true
fi
# state mismatch: PostgreSQL volume with missing postgres-password refusing to generate replacement password
if volume_exists && ! validate_secret_file "$PG_PASSWORD_FILE"; then fail "state mismatch: PostgreSQL volume $pg_volume exists but $PG_PASSWORD_FILE is missing, empty, or not mode 0600; refusing to generate replacement password"; fi
ensure_secret_file "$PG_PASSWORD_FILE" || fail "invalid PostgreSQL password secret file permissions/content"
PG_PASS="$(cat "$PG_PASSWORD_FILE")"
POSTGRES_USER="vpnsale"; POSTGRES_DB="vpnsale"
ASYNC_DB_URL="$(build_pg_url '+asyncpg' "$POSTGRES_USER" "$PG_PASS" postgres 5432 "$POSTGRES_DB")"
SYNC_DB_URL="$(build_pg_url '' "$POSTGRES_USER" "$PG_PASS" postgres 5432 "$POSTGRES_DB")"
printf 'Re-rendering runtime env file from preserved secret sources: %s\n' "$ENV_FILE" >&2
: >"$ENV_FILE"; chmod 600 "$ENV_FILE"
set_kv_atomic "$ENV_FILE" VPN_SALE_ENVIRONMENT TEST; set_kv_atomic "$ENV_FILE" POSTGRES_USER "$POSTGRES_USER"; set_kv_atomic "$ENV_FILE" POSTGRES_DB "$POSTGRES_DB"; set_kv_atomic "$ENV_FILE" POSTGRES_PASSWORD "$PG_PASS"; set_kv_atomic "$ENV_FILE" VPN_SALE_DATABASE_URL "$ASYNC_DB_URL"; set_kv_atomic "$ENV_FILE" DATABASE_URL "$ASYNC_DB_URL"; set_kv_atomic "$ENV_FILE" VPN_SALE_SYNC_DATABASE_URL "$SYNC_DB_URL"; set_kv_atomic "$ENV_FILE" VPN_SALE_REDIS_URL redis://redis:6379/0
for k in VPN_SALE_IDENTITY_ENCRYPTION_KEY VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY VPN_SALE_ADMIN_CSRF_SECRET VPN_SALE_CUSTOMER_CSRF_SECRET VPN_SALE_TELEGRAM_RATE_LIMIT_KEY; do f="$SECRETS_DIR/$k"; ensure_secret_file "$f"; set_kv_atomic "$ENV_FILE" "$k" "$(cat "$f")"; done
CUSTOMER_ORIGIN="https://app.$DOMAIN"; API_ORIGIN="https://api.$DOMAIN"; ADMIN_ORIGIN="https://admin.$DOMAIN"; RESELLER_ORIGIN="https://reseller.$DOMAIN"
BOT_TOKEN=""; if [[ -n "$TELEGRAM_BOT_TOKEN_FILE" ]]; then validate_secret_file "$TELEGRAM_BOT_TOKEN_FILE" || fail "telegram token file must exist, be non-empty, and have mode 0600"; BOT_TOKEN="$(tr -d '\r\n' <"$TELEGRAM_BOT_TOKEN_FILE")"; fi
if [[ "$ENABLE_TELEGRAM" == true && -z "$BOT_TOKEN" && "$NON_INTERACTIVE" == false ]]; then read -r -s -p 'Telegram bot token: ' BOT_TOKEN </dev/tty; printf '\n' >/dev/tty; fi
[[ "$ENABLE_TELEGRAM" == false || -n "$BOT_TOKEN" ]] || fail "telegram token required via --telegram-bot-token-file or hidden prompt"
if [[ "$ENABLE_TELEGRAM" == true ]]; then me_json="$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$BOT_TOKEN" | curl -fsS --retry 2 --connect-timeout 5 --config -)"; [[ "$(jq -r '.ok' <<<"$me_json")" == true ]] || fail "Telegram getMe failed"; derived_username="$(jq -r '.result.username // empty' <<<"$me_json")"; [[ -n "$derived_username" ]] || fail "Telegram getMe returned no username"; [[ -z "$TELEGRAM_BOT_USERNAME" || "$TELEGRAM_BOT_USERNAME" == "$derived_username" ]] || fail "provided Telegram username does not match getMe"; TELEGRAM_BOT_USERNAME="$derived_username"; else TELEGRAM_BOT_USERNAME="disabled_bot"; fi
set_kv_atomic "$ENV_FILE" VPN_SALE_IDENTITY_ENCRYPTION_KEY_VERSION test-v1; set_kv_atomic "$ENV_FILE" VPN_SALE_API_PUBLIC_ORIGIN "$API_ORIGIN"; set_kv_atomic "$ENV_FILE" VPN_SALE_PUBLIC_APP_ORIGIN "$CUSTOMER_ORIGIN"; set_kv_atomic "$ENV_FILE" VPN_SALE_CUSTOMER_API_FRONTEND_URL "$API_ORIGIN"; set_kv_atomic "$ENV_FILE" VPN_SALE_CORS_ALLOWED_ORIGINS "[\"$CUSTOMER_ORIGIN\",\"$ADMIN_ORIGIN\",\"$RESELLER_ORIGIN\"]"; set_kv_atomic "$ENV_FILE" VPN_SALE_CUSTOMER_APP_NAME "VPN-SALE Test"; set_kv_atomic "$ENV_FILE" VPN_SALE_TELEGRAM_BOT_USERNAME "$TELEGRAM_BOT_USERNAME"; set_kv_atomic "$ENV_FILE" VPN_SALE_TELEGRAM_BOT_TOKEN "$BOT_TOKEN"; set_kv_atomic "$ENV_FILE" VPN_SALE_BOT_ENABLED "$ENABLE_TELEGRAM"; set_kv_atomic "$ENV_FILE" VPN_SALE_BOT_MODE "$([[ "$ENABLE_TELEGRAM" == true ]] && echo polling || echo disabled)"; set_kv_atomic "$ENV_FILE" VPN_SALE_CUSTOMER_MINI_APP_URL "$CUSTOMER_ORIGIN"; set_kv_atomic "$ENV_FILE" VPN_SALE_CUSTOMER_MINI_APP_ALLOWED_HOSTS "app.$DOMAIN"; set_kv_atomic "$ENV_FILE" VPN_SALE_PROVIDER_WRITES_ENABLED false; set_kv_atomic "$ENV_FILE" VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED false; set_kv_atomic "$ENV_FILE" VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED false
for k in POSTGRES_PASSWORD VPN_SALE_DATABASE_URL POSTGRES_USER POSTGRES_DB VPN_SALE_REDIS_URL VPN_SALE_API_PUBLIC_ORIGIN VPN_SALE_PUBLIC_APP_ORIGIN VPN_SALE_TELEGRAM_BOT_USERNAME; do [[ -n "$(get_env "$k" "$ENV_FILE")" ]] || fail "missing required config $k"; done
phase_done secrets
phase="compose render"
./scripts/verify-test-server-compose.sh "$ENV_FILE"
"${compose[@]}" config >/tmp/vpn-sale-compose.rendered.yml
! grep -Eq '0\.0\.0\.0:(5432|6379)|:(5432|6379):(5432|6379)' /tmp/vpn-sale-compose.rendered.yml || fail "PostgreSQL or Redis host binding detected"
phase_done compose
phase="build images"
profiles=( ); [[ "$ENABLE_TELEGRAM" == true ]] && profiles=(--profile telegram)
"${compose[@]}" "${profiles[@]}" build api worker customer-web admin-web reseller-web telegram-bot
phase_done build
phase="database and redis"
"${compose[@]}" up -d postgres redis
for svc in postgres redis; do wait_compose_service_healthy "$svc" 120 "${compose[@]}" || fail "$svc did not become healthy"; done
"${compose[@]}" exec -T postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null || fail "PostgreSQL is not ready for configured role/database"
phase_done database
phase="migrations"
"${compose[@]}" run --rm --no-deps api alembic -c /app/apps/api/alembic.ini upgrade head
phase_done migrations
phase="start services"
start_services=(api customer-web admin-web reseller-web); [[ "$ENABLE_TELEGRAM" == true ]] && start_services+=(telegram-bot)
"${compose[@]}" "${profiles[@]}" up -d "${start_services[@]}"
./scripts/wait-for-http.sh http://127.0.0.1:8000/health 60; ./scripts/wait-for-http.sh http://127.0.0.1:8000/ready 60
for p in 3000 3001 3002; do ./scripts/wait-for-http.sh "http://127.0.0.1:$p" 60; done
phase_done services
phase="Caddy"
tmp_caddy="$(mktemp)"
render_managed_caddyfile "$DOMAIN" >"$tmp_caddy"
! grep -Fq 'fast.dr-ping.com' "$tmp_caddy" || fail "forbidden hostname rendered"
activate_managed_caddyfile "$tmp_caddy" "$CADDY_MARKER" || fail "Caddy activation failed"
phase_done caddy
phase="Telegram setup"
if [[ "$ENABLE_TELEGRAM" == true ]]; then printf 'url = "https://api.telegram.org/bot%s/deleteWebhook"\n' "$BOT_TOKEN" | curl -fsS --config - -d drop_pending_updates=true >/dev/null; fi
phase="smoke tests"
if [[ "$SKIP_DNS" != true ]]; then for u in "$CUSTOMER_ORIGIN" "$API_ORIGIN/health" "$ADMIN_ORIGIN" "$RESELLER_ORIGIN"; do ./scripts/wait-for-http.sh "$u" 120; done; fi
VPN_SALE_TEST_SERVER_ENV_FILE="$ENV_FILE" VPN_SALE_TEST_SERVER_DOMAIN="$DOMAIN" ./scripts/smoke-test-test-server.sh
phase_done complete
printf 'Test server deployment completed for %s at commit %s\nRuntime: %s\nVerify: %s/scripts/verify-test-server.sh --domain %s --env-file %s\n' "$DOMAIN" "$(git rev-parse HEAD)" "$RUNTIME_DIR" "$INSTALL_DIR" "$DOMAIN" "$ENV_FILE"
