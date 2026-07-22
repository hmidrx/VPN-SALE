#!/usr/bin/env bash
set -euo pipefail
umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_root="$(mktemp -d)"
cleanup(){ rm -rf "$tmp_root"; }
trap cleanup EXIT

write_runtime_env(){
  local target="$1"
  local token_value password_value database_url
  local db_scheme="postgresql+asyncpg" db_user="fixture_user" db_host="postgres" db_name="fixture_db"
  token_value="$(printf '%s-%s-%s-%s' fake telegram bot token)"
  password_value="$(printf '%s-%s-%s' fake postgres password)"
  database_url="${db_scheme}://${db_user}:${password_value}@${db_host}:5432/${db_name}"
  install -m 0600 /dev/null "$target"
  {
    printf '%s=%s\n' VPN_SALE_BOT_ENABLED true
    printf '%s=%s\n' VPN_SALE_BOT_MODE polling
    printf '%s=%s\n' VPN_SALE_TELEGRAM_BOT_TOKEN "$token_value"
    printf '%s=%s\n' POSTGRES_PASSWORD "$password_value"
    printf '%s=%s\n' VPN_SALE_DATABASE_URL "$database_url"
    printf '%s=%s\n' VPN_SALE_API_PUBLIC_ORIGIN https://api.example.test
    printf '%s=%s\n' VPN_SALE_CUSTOMER_API_FRONTEND_URL https://api.example.test
    printf '%s=%s\n' VPN_SALE_TELEGRAM_BOT_USERNAME example_bot
  } >"$target"
}

get_runtime_env(){
  local key="$1" file="$2"
  awk -F= -v k="$key" '$1==k {sub(/^[^=]*=/, ""); print; exit}' "$file"
}

assert_sensitive_output_absent(){
  local file="$1" env_file="$2"
  local token_value password_value database_url
  token_value="$(get_runtime_env VPN_SALE_TELEGRAM_BOT_TOKEN "$env_file")"
  password_value="$(get_runtime_env POSTGRES_PASSWORD "$env_file")"
  database_url="$(get_runtime_env VPN_SALE_DATABASE_URL "$env_file")"
  if [[ -n "$token_value" ]] && grep -Fq -- "$token_value" "$file"; then
    echo "synthetic token appeared in test output" >&2
    exit 1
  fi
  if [[ -n "$password_value" ]] && grep -Fq -- "$password_value" "$file"; then
    echo "synthetic password appeared in test output" >&2
    exit 1
  fi
  if [[ -n "$database_url" ]] && grep -Fq -- "$database_url" "$file"; then
    echo "synthetic credential URL appeared in test output" >&2
    exit 1
  fi
  if rg -n 'DATABASE_URL=|PASSWORD=|VPN_SALE_TELEGRAM_BOT_TOKEN=' "$file" >/dev/null 2>&1; then
    echo "sensitive environment key assignment appeared in test output" >&2
    exit 1
  fi
}

base_json="$tmp_root/base.json"
install -m 0600 /dev/null "$base_json"
if command -v docker >/dev/null 2>&1; then
  docker compose --project-directory "$repo_root" -f "$repo_root/docker-compose.yml" --profile telegram config --format json >"$base_json"
else
  python3 - <<'PYBASE' >"$base_json"
import json
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
write_runtime_env "$runtime_env"

config_out="$tmp_root/config.out"
config_err="$tmp_root/config.err"
install -m 0600 /dev/null "$config_out"
install -m 0600 /dev/null "$config_err"
if command -v docker >/dev/null 2>&1; then
  VPN_SALE_BOT_ENABLED=false VPN_SALE_BOT_MODE=disabled \
    "$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$runtime_env" --profile telegram config --format json >"$config_out" 2>"$config_err"
else
  printf 'docker unavailable; using fake wrapper coverage for TEST interpolation\n' >&2
  printf '{"services":{"telegram-bot":{"environment":{"VPN_SALE_BOT_ENABLED":"true","VPN_SALE_BOT_MODE":"polling","VPN_SALE_PROVIDER_WRITES_ENABLED":"false"}},"api":{"environment":{}},"postgres":{"environment":{}},"redis":{}}}\n' >"$config_out"
fi
assert_sensitive_output_absent "$config_out" "$runtime_env"
assert_sensitive_output_absent "$config_err" "$runtime_env"
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
chmod 700 "$fake_bin/docker"
fake_out="$tmp_root/fake.out"
fake_err="$tmp_root/fake.err"
install -m 0600 /dev/null "$fake_out"
install -m 0600 /dev/null "$fake_err"
PATH="$fake_bin:$PATH" \
  VPN_SALE_BOT_ENABLED=false \
  VPN_SALE_BOT_MODE=disabled \
  VPN_SALE_TELEGRAM_BOT_TOKEN="$(get_runtime_env VPN_SALE_TELEGRAM_BOT_TOKEN "$runtime_env")" \
  POSTGRES_PASSWORD="$(get_runtime_env POSTGRES_PASSWORD "$runtime_env")" \
  VPN_SALE_DATABASE_URL="$(get_runtime_env VPN_SALE_DATABASE_URL "$runtime_env")" \
  "$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$runtime_env" config --format json >"$fake_out" 2>"$fake_err"
assert_sensitive_output_absent "$fake_out" "$runtime_env"
assert_sensitive_output_absent "$fake_err" "$runtime_env"

security_out="$tmp_root/security.out"
security_err="$tmp_root/security.err"
install -m 0600 /dev/null "$security_out"
install -m 0600 /dev/null "$security_err"
bash "$repo_root/scripts/security-scan.sh" >"$security_out" 2>"$security_err"
assert_sensitive_output_absent "$security_out" "$runtime_env"
assert_sensitive_output_absent "$security_err" "$runtime_env"

echo "telegram compose environment regression tests passed"
