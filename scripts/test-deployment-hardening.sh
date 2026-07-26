#!/usr/bin/env bash
# shellcheck disable=SC2016
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
installer="$repo_root/scripts/install-test-server.sh"
smoke="$repo_root/scripts/smoke-test-test-server.sh"
doc="$repo_root/docs/TEST_SERVER_DEPLOYMENT.md"
compose_file="$repo_root/docker-compose.test-server.yml"
python3 - <<'PY'
from urllib.parse import quote, unquote, urlparse
raw = 'p@ss%:/# word'
url = f"postgresql+asyncpg://vpnsale:{quote(raw, safe='')}@postgres:5432/vpnsale"
assert unquote(urlparse(url).password or '') == raw
assert '%40' in url and '%25' in url and '%3A' in url and '%2F' in url and '%23' in url and '%20' in url
assert url.replace('%', '%%').count('%%') >= 6
PY
bash -n "$installer" "$smoke" "$repo_root/scripts/vpn-sale-compose-test-server" "$repo_root/scripts/test-server-compose-json.sh" "$repo_root/scripts/test-compose-ps-json.sh"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$installer" "$smoke" "$repo_root/scripts/vpn-sale-compose-test-server" "$repo_root/scripts/test-server-compose-json.sh" "$repo_root/scripts/test-compose-ps-json.sh"; fi

search(){
  local pattern="$1"; shift
  if command -v rg >/dev/null 2>&1; then
    rg -n -- "$pattern" "$@"
  else
    grep -En -- "$pattern" "$@"
  fi
}
require_match(){ search "$@" >/dev/null; }
reject_match(){ ! search "$@" >/dev/null; }
count_matches(){ search "$@" 2>/dev/null | wc -l; }

require_match 'REF="main"' "$installer"
reject_match 'fix/deployment-hardening' "$installer" "$doc"
require_match 'raw.githubusercontent.com/hmidrx/VPN-SALE/main/scripts/install-test-server.sh' "$doc"
reject_match 'apt-get install .*ufw|ufw enable|email off|docker compose down -v|\|\| true.*pull' "$installer" "$doc" "$compose_file"
require_match '--reset-disposable-postgres' "$installer" "$doc"
require_match 'chmod 600 "[$]ENV_FILE"|install -d -m 0700 "[$]RUNTIME_DIR"' "$installer"
require_match 'urlencode\(\)|urllib.parse.quote\(os.environ\["RAW_VALUE"\], safe=""\)' "$installer"
require_match 'alembic -c /app/apps/api/alembic.ini upgrade head' "$installer" "$smoke"
require_match 'build api customer-web admin-web reseller-web telegram-bot|up -d postgres redis|up -d "\$\{start_services\[@\]\}"|Caddy|wait-for-http|smoke-test-test-server.sh' "$installer"
require_match 'test-server-compose-json.sh|wait_compose_service_healthy|# vpn-sale-test-server-managed|is_installer_managed_caddy|ripgrep nodejs npm' "$installer"
require_match 'deleteWebhook|setMyCommands|setChatMenuButton|getChatMenuButton|getMe' "$installer" "$smoke"
if search 'test_bot' "$installer" "$compose_file" >/dev/null; then echo 'placeholder test_bot found' >&2; exit 1; fi
(( $(count_matches 'ports: !reset \[\]' "$compose_file") >= 2 ))
require_match 'profiles: !override \["ops"\]' "$compose_file"
require_match '127\.0\.0\.1:8000:8000|127\.0\.0\.1:3000:3000|127\.0\.0\.1:3001:3000|127\.0\.0\.1:3002:3000' "$compose_file"
require_match 'NEXT_PUBLIC_API_BASE_URL|NEXT_PUBLIC_CUSTOMER_API_BASE_URL|NEXT_PUBLIC_TELEGRAM_BOT_USERNAME|NEXT_PUBLIC_CUSTOMER_APP_NAME' "$compose_file"

valid_caddyfile="$(mktemp)"; invalid_caddyfile="$(mktemp)"
trap 'rm -f "$valid_caddyfile" "$invalid_caddyfile"' EXIT
printf '{
	email admin@example.test
}
app.example.test {
	reverse_proxy 127.0.0.1:3000
}
' >"$valid_caddyfile"
printf '{
	email off
}
app.example.test {
	reverse_proxy 127.0.0.1:3000
}
' >"$invalid_caddyfile"
bash "$smoke" --check-caddyfile "$valid_caddyfile" >/dev/null
bash "$repo_root/scripts/test-compose-ps-json.sh" >/dev/null
bash "$repo_root/scripts/test-smoke-test-test-server.sh" >/dev/null
if bash "$smoke" --check-caddyfile "$invalid_caddyfile" >/dev/null 2>&1; then echo 'invalid Caddy email off directive passed smoke check' >&2; exit 1; fi
if command -v docker >/dev/null 2>&1; then "$repo_root/scripts/verify-test-server-compose.sh"; else printf 'docker unavailable; skipped compose render\n' >&2; fi
require_match 'VPN_SALE_BOT_ENABLED: "[$]\{VPN_SALE_BOT_ENABLED:-false\}"|VPN_SALE_BOT_MODE: "[$]\{VPN_SALE_BOT_MODE:-disabled\}"' "$repo_root/docker-compose.yml"
require_match 'env -i HOME=.*PATH=.*VPN_SALE_TEST_SERVER_ENV_FILE="[$]env_file"|--env-file "[$]env_file"' "$repo_root/scripts/vpn-sale-compose-test-server"
require_match 'telegram bot must be running when enabled|VPN_SALE_BOT_ENABLED|VPN_SALE_BOT_MODE|telegram bot runtime mode is disabled' "$repo_root/scripts/verify-test-server.sh"
require_match 'telegram bot enabled but not steadily running; redacted state=' "$smoke"
reject_match 'env \| docker|printenv|VPN_SALE_TELEGRAM_BOT_TOKEN' "$repo_root/scripts/verify-test-server.sh"
printf 'deployment hardening tests passed\n'
# Hardened installer state, Caddy ownership, PostgreSQL lifecycle and verifier coverage.
require_match 'test-server-installer-lib.sh' "$installer" "$repo_root/scripts/verify-test-server.sh"
require_match 'write_state|state.json|last_completed_phase|selected_commit' "$repo_root/scripts/test-server-installer-lib.sh" "$installer"
require_match 'ensure_secret_file|atomic_write_file|mktemp .*mv -f|chmod 600|umask 077' "$repo_root/scripts/test-server-installer-lib.sh" "$installer"
require_match 'state mismatch: PostgreSQL volume .*postgres-password.*refusing to generate replacement password' "$installer"
require_match 'docker rm -f "\$pg_container"|docker volume rm "\$pg_volume"' "$installer"
reject_match 'down -v' "$installer" "$repo_root/scripts/vpn-sale-compose-test-server"
require_match 'pg_isready -U "\$POSTGRES_USER" -d "\$POSTGRES_DB"' "$installer"
reject_match '-U postgres|role "postgres"|vpnsale_test' "$installer" "$repo_root/scripts/verify-test-server.sh"
require_match 'build_pg_url|VPN_SALE_SYNC_DATABASE_URL|urlencode_secret' "$installer" "$repo_root/scripts/test-server-installer-lib.sh"
require_match 'is_default_caddyfile|is_managed_caddyfile|stop_safe_caddy|render_managed_caddyfile|X-Forwarded-Proto|/metrics|/internal|fast\.dr-ping\.com' "$installer" "$repo_root/scripts/test-server-installer-lib.sh"
require_match 'env -i HOME=.*docker compose.*--project-name vpn-sale|--env-file "\$env_file"' "$repo_root/scripts/vpn-sale-compose-test-server"
require_match 'verify-test-server.sh --domain|ports 80 and 443 owned|fast.dr-ping.com absent' "$doc" "$repo_root/scripts/verify-test-server.sh"
python3 - <<'PY'
from pathlib import Path
lib = Path('scripts/test-server-installer-lib.sh').read_text()
assert 'fast.dr-ping.com' not in ''.join(line for line in lib.splitlines() if line.startswith(('app.', 'api.', 'admin.', 'reseller.')))
raw = "aa@@bb%:/#' spaced"
from urllib.parse import quote, unquote, urlparse
url = f"postgresql+asyncpg://vpnsale:{quote(raw, safe='')}@postgres:5432/vpnsale"
assert unquote(urlparse(url).password or '') == raw
assert url.count('%40') == 2 and '%27' in url and '%20' in url
PY
