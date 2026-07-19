#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 - <<'PY'
from urllib.parse import quote, unquote, urlparse
raw = 'Yaghii@@118'
url = f"postgresql+asyncpg://vpnsale:{quote(raw, safe='')}@postgres:5432/vpnsale"
assert unquote(urlparse(url).password or '') == raw
assert url.replace('%', '%%').count('%%40') == 2
PY
bash -n "$repo_root/scripts/install-test-server.sh" "$repo_root/scripts/smoke-test-test-server.sh" "$repo_root/scripts/vpn-sale-compose-test-server"
if command -v shellcheck >/dev/null 2>&1; then shellcheck "$repo_root/scripts/install-test-server.sh" "$repo_root/scripts/smoke-test-test-server.sh" "$repo_root/scripts/vpn-sale-compose-test-server"; fi
if command -v docker >/dev/null 2>&1; then "$repo_root/scripts/verify-test-server-compose.sh"; else printf 'docker unavailable; skipped compose render\n' >&2; fi
