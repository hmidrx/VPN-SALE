#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
nginx="$root/infra/reverse-proxy/nginx.conf"
caddy="$root/infra/deployment/test-server/Caddyfile.example"
installer="$root/scripts/test-server-installer-lib.sh"
install_script="$root/scripts/install-test-server.sh"
prefix='/api/v1/internal/telegram'

grep -Fq "location = $prefix { return 404; }" "$nginx"
grep -Fq "location ^~ $prefix/ { return 404; }" "$nginx"
grep -Fq "path $prefix $prefix/*" "$caddy"
grep -Fq "path $prefix $prefix/*" "$installer"
grep -Fq 'ensure_secret_file "$TELEGRAM_INTERNAL_TOKEN_FILE"' "$install_script"
grep -Fq 'VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST' "$install_script"
! grep -Eq 'VPN_SALE_TELEGRAM_INTERNAL_(TOKEN|SECRET)=[^$]' "$root/.env.example"
printf 'telegram internal boundary checks passed\n'
