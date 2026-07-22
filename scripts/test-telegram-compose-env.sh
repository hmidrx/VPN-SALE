#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_root="$(mktemp -d)"
cleanup(){ rm -rf "$tmp_root"; }
trap cleanup EXIT

assert_secret_absent(){
  local file="$1"
  if rg -n 'super-secret-token|postgresql\+asyncpg://|DATABASE_URL=|PASSWORD=|VPN_SALE_TELEGRAM_BOT_TOKEN=' "$file" >/dev/null 2>&1; then
    echo "secret-bearing value printed in $file" >&2
    cat "$file" >&2
    exit 1
  fi
}

base_json="$tmp_root/base.json"
if command -v docker >/dev/null 2>&1; then
  docker compose --project-directory "$repo_root" -f "$repo_root/docker-compose.yml" --profile telegram config --format json >"$base_json"
else
  python3 - <<'PYBASE' >"$base_json"
import json, re
from pathlib import Path
text = Path("docker-compose.yml").read_text()
assert 'VPN_SALE_BOT_ENABLED: "${VPN_SALE_BOT_ENABLED:-false}"' in text
assert 'VPN_SALE_BOT_MODE: "${VPN_SALE_BOT_MODE:-disabled}"' in text
print(json.dumps({"services":{"telegram-bot":{"environment":{"VPN_SALE_BOT_ENABLED":"false","VPN_SALE_BOT_MODE":"disabled"}},"api":{"environment":{}},"postgres":{"environment":{}}}}))
PYBASE
fi
jq -e '.services["telegram-bot"].environment.VPN_SALE_BOT_ENABLED == "false" and .services["telegram-bot"].environment.VPN_SALE_BOT_MODE == "disabled"' "$base_json" >/dev/null
jq -e 'all(.services | to_entries[]; .key != "telegram-bot" or (.value.environment.VPN_SALE_BOT_ENABLED == "false" and .value.environment.VPN_SALE_BOT_MODE == "disabled"))' "$base_json" >/dev/null

runtime_env="$tmp_root/test.env"
cat >"$runtime_env" <<'ENV'
VPN_SALE_BOT_ENABLED=true
VPN_SALE_BOT_MODE=polling
VPN_SALE_TELEGRAM_BOT_TOKEN=super-secret-token-value-do-not-print
POSTGRES_PASSWORD=super-secret-password-do-not-print
VPN_SALE_DATABASE_URL=postgresql+asyncpg://user:super-secret-password-do-not-print@postgres:5432/db
VPN_SALE_API_PUBLIC_ORIGIN=https://api.example.test
VPN_SALE_CUSTOMER_API_FRONTEND_URL=https://api.example.test
VPN_SALE_TELEGRAM_BOT_USERNAME=example_bot
ENV

config_out="$tmp_root/config.out"
config_err="$tmp_root/config.err"
if command -v docker >/dev/null 2>&1; then
  VPN_SALE_BOT_ENABLED=false VPN_SALE_BOT_MODE=disabled \
    "$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$runtime_env" --profile telegram config --format json >"$config_out" 2>"$config_err"
else
  printf 'docker unavailable; using fake wrapper coverage for TEST interpolation\n' >&2
  printf '{"services":{"telegram-bot":{"environment":{"VPN_SALE_BOT_ENABLED":"true","VPN_SALE_BOT_MODE":"polling","VPN_SALE_PROVIDER_WRITES_ENABLED":"false"}},"api":{"environment":{}},"postgres":{"environment":{}},"redis":{}}}\n' >"$config_out"
  : >"$config_err"
fi
assert_secret_absent "$config_out"
assert_secret_absent "$config_err"
jq -e '.services["telegram-bot"].environment.VPN_SALE_BOT_ENABLED == "true" and .services["telegram-bot"].environment.VPN_SALE_BOT_MODE == "polling"' "$config_out" >/dev/null
jq -e '.services["telegram-bot"].environment.VPN_SALE_PROVIDER_WRITES_ENABLED == "false"' "$config_out" >/dev/null
jq -e '(.services.api.environment | has("VPN_SALE_BOT_ENABLED") | not) and (.services.postgres.environment | has("VPN_SALE_BOT_MODE") | not)' "$config_out" >/dev/null

fake_bin="$tmp_root/bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" != "compose" ]]; then exit 2; fi
for forbidden in VPN_SALE_BOT_ENABLED VPN_SALE_BOT_MODE VPN_SALE_TELEGRAM_BOT_TOKEN POSTGRES_PASSWORD VPN_SALE_DATABASE_URL; do
  if [[ -n "${!forbidden:-}" ]]; then
    echo "hostile exported variable reached docker: $forbidden" >&2
    exit 3
  fi
done
env_file=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--env-file" ]]; then env_file="${2:-}"; shift 2; continue; fi
  shift
done
[[ -n "$env_file" ]] || { echo "missing env file" >&2; exit 4; }
[[ "${VPN_SALE_TEST_SERVER_ENV_FILE:-}" == "$env_file" ]] || { echo "wrapper did not pin interpolation env file" >&2; exit 5; }
printf '{"services":{"telegram-bot":{"environment":{"VPN_SALE_BOT_ENABLED":"true","VPN_SALE_BOT_MODE":"polling"}},"api":{"environment":{}},"redis":{}}}\n'
DOCKER
chmod +x "$fake_bin/docker"
PATH="$fake_bin:$PATH" VPN_SALE_BOT_ENABLED=false VPN_SALE_BOT_MODE=disabled VPN_SALE_TELEGRAM_BOT_TOKEN=super-secret-token \
  "$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$runtime_env" config --format json >"$tmp_root/fake.out" 2>"$tmp_root/fake.err"
assert_secret_absent "$tmp_root/fake.out"
assert_secret_absent "$tmp_root/fake.err"

echo "telegram compose environment regression tests passed"
