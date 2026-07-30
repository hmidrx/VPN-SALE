#!/usr/bin/env bash
# shellcheck disable=SC2016 # Assertions intentionally match literal shell source.
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
grep -Fq 'ensure_container_secret_source "$TELEGRAM_INTERNAL_TOKEN_FILE"' "$install_script"
grep -Fq 'VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST' "$install_script"
grep -Fq 'prepare_container_secret_file "$TELEGRAM_INTERNAL_TOKEN_FILE" "$api_gid"' "$install_script"
grep -Fq '[[ "$api_gid" == "$bot_gid" ]]' "$install_script"
grep -Fq 'ensure_container_secret_source(){' "$installer"
grep -Fq '[[ "$(stat -c %u:%g:%a "$file")" == "0:$gid:640" && -s "$file" ]]' "$installer"
grep -Fq '[[ "$(stat -c %u:%a "$SECRETS_DIR")" == "0:700" ]]' "$install_script"
grep -Fq 'api_secret_fingerprint=' "$install_script"
grep -Fq 'bot_secret_fingerprint=' "$install_script"
grep -Fq 'unset api_secret_fingerprint bot_secret_fingerprint' "$install_script"
if grep -Eq 'VPN_SALE_TELEGRAM_INTERNAL_(TOKEN|SECRET)=[^$]' "$root/.env.example"; then exit 1; fi
printf 'telegram internal boundary checks passed\n'
