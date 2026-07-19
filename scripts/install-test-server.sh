#!/usr/bin/env bash
set -euo pipefail
phase="initialization"
fail(){ printf 'ERROR during %s: %s\n' "$phase" "$*" >&2; printf 'Safe diagnostics: docker compose ps; journalctl -u caddy --no-pager -n 80; docker compose logs api --tail=80\n' >&2; exit 1; }
trap 'fail "command failed on line $LINENO"' ERR
DOMAIN=""; REPO="https://github.com/hmidrx/VPN-SALE.git"; REF="fix/deployment-hardening"; RUNTIME_DIR="/opt/vpn-sale-runtime"; ENABLE_TELEGRAM=false; RESET_PG=false; SKIP_DNS=false; NON_INTERACTIVE=false; OVERRIDE_OS=false
while [[ $# -gt 0 ]]; do case "$1" in --domain) DOMAIN="$2"; shift 2;; --repo) REPO="$2"; shift 2;; --ref) REF="$2"; shift 2;; --runtime-dir) RUNTIME_DIR="$2"; shift 2;; --enable-telegram) ENABLE_TELEGRAM=true; shift;; --reset-disposable-postgres) RESET_PG=true; shift;; --skip-dns-wait) SKIP_DNS=true; shift;; --non-interactive) NON_INTERACTIVE=true; shift;; --allow-unsupported-os) OVERRIDE_OS=true; shift;; *) fail "unknown option $1";; esac; done
[[ $(id -u) -eq 0 ]] || fail "must run as root"
[[ -n "$DOMAIN" ]] || fail "--domain is required; no implicit production domain is used"
phase="preflight"
. /etc/os-release
[[ "${VERSION_ID:-}" == "24.04" || "$OVERRIDE_OS" == true ]] || fail "Ubuntu 24.04 required (or --allow-unsupported-os)"
printf 'CPU: %s cores; RAM: %s MiB; Disk: %s\n' "$(nproc)" "$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)" "$(df -h / | awk 'NR==2{print $4 " free"}')"
for p in 80 443; do ss -ltn "sport = :$p" | awk 'NR>1{exit 1}' || fail "port $p is already in use"; done
CUSTOMER_ORIGIN="https://app.$DOMAIN"; API_ORIGIN="https://api.$DOMAIN"; ADMIN_ORIGIN="https://admin.$DOMAIN"; RESELLER_ORIGIN="https://reseller.$DOMAIN"
if [[ "$SKIP_DNS" != true ]]; then for h in "app.$DOMAIN" "api.$DOMAIN" "admin.$DOMAIN" "reseller.$DOMAIN"; do getent ahosts "$h" >/dev/null || fail "DNS missing for $h"; done; fi
phase="install packages"
apt-get update
apt-get install -y git curl jq ca-certificates gnupg openssl python3 fail2ban
install -m 0755 -d /etc/apt/keyrings
if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc; chmod a+r /etc/apt/keyrings/docker.asc; fi
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$(dpkg --print-architecture)" "${VERSION_CODENAME}" >/etc/apt/sources.list.d/docker.list
if [[ ! -f /etc/apt/keyrings/caddy-stable-archive-keyring.gpg ]]; then curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /etc/apt/keyrings/caddy-stable-archive-keyring.gpg; fi
printf 'deb [signed-by=/etc/apt/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main\n' >/etc/apt/sources.list.d/caddy-stable.list
apt-get update; apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin caddy
phase="swap"
if [[ $(swapon --show --noheadings | wc -l) -eq 0 ]]; then fallocate -l 4G /swapfile; chmod 600 /swapfile; mkswap /swapfile >/dev/null; swapon /swapfile; grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab; fi
phase="checkout"
if [[ -d /opt/vpn-sale/.git ]]; then git -C /opt/vpn-sale fetch --all --prune; git -C /opt/vpn-sale checkout "$REF"; git -C /opt/vpn-sale pull --ff-only || true; else git clone --branch "$REF" "$REPO" /opt/vpn-sale; fi
phase="runtime env"
install -d -m 0700 "$RUNTIME_DIR"
ENV_FILE="$RUNTIME_DIR/test.env"
read_secret(){ local prompt="$1" var; if [[ "$NON_INTERACTIVE" == true ]]; then cat; else read -r -s -p "$prompt: " var; printf '\n' >&2; printf '%s' "$var"; fi; }
gen(){ python3 -c 'import secrets; print(secrets.token_urlsafe(48))'; }
PG_PASS="${POSTGRES_PASSWORD:-$(gen)}"; BOT_TOKEN="${VPN_SALE_TELEGRAM_BOT_TOKEN:-}"; [[ "$ENABLE_TELEGRAM" == false || -n "$BOT_TOKEN" || "$NON_INTERACTIVE" == false ]] && true || fail "telegram token required"
if [[ "$ENABLE_TELEGRAM" == true && -z "$BOT_TOKEN" ]]; then BOT_TOKEN="$(read_secret 'Telegram bot token')"; fi
DB_URL="$(POSTGRES_PASSWORD="$PG_PASS" python3 - <<'PY'
import os, urllib.parse
p=urllib.parse.quote(os.environ['POSTGRES_PASSWORD'], safe='')
print(f'postgresql+asyncpg://vpnsale_test:{p}@postgres:5432/vpnsale_test')
PY
)"
install -m 0600 /dev/null "$ENV_FILE"
cat >"$ENV_FILE" <<EOF
VPN_SALE_ENVIRONMENT=TEST
POSTGRES_USER=vpnsale_test
POSTGRES_DB=vpnsale_test
POSTGRES_PASSWORD=$PG_PASS
VPN_SALE_DATABASE_URL=$DB_URL
DATABASE_URL=$DB_URL
VPN_SALE_REDIS_URL=redis://redis:6379/0
VPN_SALE_IDENTITY_ENCRYPTION_KEY=$(python3 - <<'PY'
import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())
PY
)
VPN_SALE_IDENTITY_ENCRYPTION_KEY_VERSION=test-v1
VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY=$(gen)
VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY=$(gen)
VPN_SALE_ADMIN_CSRF_SECRET=$(gen)
VPN_SALE_CUSTOMER_CSRF_SECRET=$(gen)
VPN_SALE_API_PUBLIC_ORIGIN=$API_ORIGIN
VPN_SALE_PUBLIC_APP_ORIGIN=$CUSTOMER_ORIGIN
VPN_SALE_CUSTOMER_API_FRONTEND_URL=$API_ORIGIN
VPN_SALE_CORS_ALLOWED_ORIGINS=["$CUSTOMER_ORIGIN","$ADMIN_ORIGIN","$RESELLER_ORIGIN"]
VPN_SALE_CUSTOMER_APP_NAME=VPN-SALE Test
VPN_SALE_TELEGRAM_BOT_USERNAME=${VPN_SALE_TELEGRAM_BOT_USERNAME:-test_bot}
VPN_SALE_TELEGRAM_BOT_TOKEN=$BOT_TOKEN
VPN_SALE_BOT_ENABLED=$ENABLE_TELEGRAM
VPN_SALE_BOT_MODE=$( [[ "$ENABLE_TELEGRAM" == true ]] && echo polling || echo disabled )
VPN_SALE_CUSTOMER_MINI_APP_URL=$CUSTOMER_ORIGIN
VPN_SALE_CUSTOMER_MINI_APP_ALLOWED_HOSTS=app.$DOMAIN
VPN_SALE_TELEGRAM_RATE_LIMIT_KEY=$(gen)
VPN_SALE_PROVIDER_WRITES_ENABLED=false
VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED=false
VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED=false
EOF
chmod 600 "$ENV_FILE"
phase="compose render"
/opt/vpn-sale/scripts/verify-test-server-compose.sh "$ENV_FILE"
printf 'Installer preflight/render completed. Continue with smoke script after starting services. URLs: %s %s %s %s\n' "$CUSTOMER_ORIGIN" "$API_ORIGIN" "$ADMIN_ORIGIN" "$RESELLER_ORIGIN"
