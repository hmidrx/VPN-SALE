#!/usr/bin/env bash
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
bash -n "$installer" "$smoke" "$repo_root/scripts/vpn-sale-compose-test-server"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$installer" "$smoke" "$repo_root/scripts/vpn-sale-compose-test-server"; fi
rg -n 'REF="main"' "$installer" >/dev/null
! rg -n 'fix/deployment-hardening' "$installer" "$doc"
rg -n 'raw.githubusercontent.com/hmidrx/VPN-SALE/main/scripts/install-test-server.sh' "$doc" >/dev/null
! rg -n 'apt-get install .*ufw|ufw enable|email off|docker compose down -v|\|\| true.*pull' "$installer" "$doc" "$compose_file"
rg -n -- '--reset-disposable-postgres' "$installer" "$doc" >/dev/null
rg -n 'chmod 600 "\$ENV_FILE"|install -d -m 0700 "\$RUNTIME_DIR"' "$installer" >/dev/null
rg -n 'urlencode\(\)|urllib.parse.quote\(os.environ\["RAW_VALUE"\], safe=""\)' "$installer" >/dev/null
rg -n 'alembic -c apps/api/alembic.ini upgrade head' "$installer" "$smoke" >/dev/null
rg -n 'build api customer-web admin-web reseller-web telegram-bot|up -d postgres redis|up -d "\$\{start_services\[@\]\}"|Caddy|wait-for-http|smoke-test-test-server.sh' "$installer" >/dev/null
rg -n 'deleteWebhook|setMyCommands|setChatMenuButton|getChatMenuButton|getMe' "$installer" "$smoke" >/dev/null
rg -n 'test_bot' "$installer" "$compose_file" && { echo 'placeholder test_bot found' >&2; exit 1; } || true
rg -n 'ports: !reset \[\]' "$compose_file" | wc -l | awk '{if ($1 < 2) exit 1}'
rg -n 'profiles: !override \["ops"\]' "$compose_file" >/dev/null
rg -n '127\.0\.0\.1:8000:8000|127\.0\.0\.1:3000:3000|127\.0\.0\.1:3001:3000|127\.0\.0\.1:3002:3000' "$compose_file" >/dev/null
rg -n 'NEXT_PUBLIC_API_BASE_URL|NEXT_PUBLIC_CUSTOMER_API_BASE_URL|NEXT_PUBLIC_TELEGRAM_BOT_USERNAME|NEXT_PUBLIC_CUSTOMER_APP_NAME' "$compose_file" >/dev/null
if command -v docker >/dev/null 2>&1; then "$repo_root/scripts/verify-test-server-compose.sh"; else printf 'docker unavailable; skipped compose render\n' >&2; fi
printf 'deployment hardening tests passed\n'
