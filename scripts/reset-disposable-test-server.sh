#!/usr/bin/env bash
set -euo pipefail
DRY_RUN=false; CONFIRMED=false
while (($#)); do case "$1" in --dry-run) DRY_RUN=true; shift;; --confirm-disposable-test-reset) CONFIRMED=true; shift;; *) echo "ERROR: unknown argument: $1" >&2; exit 64;; esac; done
[[ $(id -u) -eq 0 ]] || { echo 'ERROR: run as root' >&2; exit 1; }
[[ "$DRY_RUN" == true || "$CONFIRMED" == true ]] || { echo 'ERROR: destructive reset requires --confirm-disposable-test-reset' >&2; exit 64; }
run(){ if [[ "$DRY_RUN" == true ]]; then printf 'DRY_RUN:'; printf ' %q' "$@"; printf '\n'; else "$@"; fi; }
project=vpn-sale; compose=/opt/vpn-sale/scripts/vpn-sale-compose-test-server; env_file=/opt/vpn-sale-runtime/test.env
if [[ -x "$compose" && -f "$env_file" ]]; then run "$compose" --env-file "$env_file" down --remove-orphans --rmi local; fi
for volume in "${project}_test_server_postgres_data" "${project}_test_server_redis_data"; do if docker volume inspect "$volume" >/dev/null 2>&1; then run docker volume rm "$volume"; fi; done
if [[ -f /etc/caddy/Caddyfile ]] && grep -Fq '# vpn-sale-test-server-managed' /etc/caddy/Caddyfile; then run rm -f /etc/caddy/Caddyfile; fi
run systemctl stop vpn-sale-test-install.service
run systemctl reset-failed vpn-sale-test-install.service
run rm -rf /opt/vpn-sale /opt/vpn-sale-runtime
