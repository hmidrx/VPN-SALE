#!/usr/bin/env bash
set -euo pipefail

log() { printf '==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
template_env="$repo_root/infra/deployment/env/test-server.env.example"
temp_dir=""
cleanup() {
  if [[ -n "$temp_dir" ]]; then
    rm -rf "$temp_dir"
  fi
}
trap cleanup EXIT

validate_env_file() {
  local env_file="$1"
  [[ -f "$env_file" ]] || fail "test-server env file does not exist: $env_file"
  [[ -r "$env_file" ]] || fail "test-server env file is not readable: $env_file"
}

require_template_key() {
  local key="$1"
  grep -Eq "^${key}=.+$" "$template_env" || fail "sanitized test-server env template is missing non-empty $key"
}

validate_template() {
  [[ -f "$template_env" ]] || fail "sanitized test-server env template is missing"
  [[ -r "$template_env" ]] || fail "sanitized test-server env template is not readable"
  require_template_key VPN_SALE_TELEGRAM_BOT_USERNAME
  require_template_key VPN_SALE_TELEGRAM_BOT_TOKEN
  require_template_key POSTGRES_PASSWORD
  require_template_key VPN_SALE_DATABASE_URL
  require_template_key VPN_SALE_IDENTITY_ENCRYPTION_KEY
  require_template_key VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY
  require_template_key VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY
  require_template_key VPN_SALE_ADMIN_CSRF_SECRET
  require_template_key VPN_SALE_CUSTOMER_CSRF_SECRET
  require_template_key VPN_SALE_TELEGRAM_RATE_LIMIT_KEY

  if grep -Eiq '(vless://|vmess://|trojan://|subscription://|[0-9]+:[A-Za-z0-9_-]{32,}|https?://[^[:space:]]*(token|password|secret)[^[:space:]]*)' "$template_env"; then
    fail "sanitized test-server env template contains a secret-like value"
  fi
}

resolved_env_file=""
resolve_env_file() {
  if [[ $# -gt 1 ]]; then
    fail "usage: scripts/verify-test-server-compose.sh [test-server-env-file]"
  fi
  if [[ $# -eq 1 && -n "$1" ]]; then
    validate_env_file "$1"
    resolved_env_file="$1"
    return
  fi
  if [[ -n "${VPN_SALE_TEST_SERVER_ENV_FILE:-}" ]]; then
    validate_env_file "$VPN_SALE_TEST_SERVER_ENV_FILE"
    resolved_env_file="$VPN_SALE_TEST_SERVER_ENV_FILE"
    return
  fi

  validate_template
  temp_dir="$(mktemp -d)"
  local generated_env="$temp_dir/test-server.env"
  cp "$template_env" "$generated_env"
  chmod 600 "$generated_env"
  resolved_env_file="$generated_env"
}

assert_ports() {
  local config_json="$1"
  jq -e '
    def published($service): [.services[$service].ports[]? | "\(.host_ip // ""):\(.published):\(.target)"];
    def no_ports($service): ((.services[$service].ports // []) | length) == 0;
    def all_bindings: [.services | to_entries[] | .value.ports[]? | "\(.host_ip // ""):\(.published):\(.target)"];
    def no_unsafe_hosts: [.services | to_entries[] | .value.ports[]? | select((.host_ip // "") == "" or .host_ip == "0.0.0.0" or .host_ip == "::")] | length == 0;
    def no_duplicates: (all_bindings | length) == (all_bindings | unique | length);
    published("api") == ["127.0.0.1:8000:8000"] and
    published("customer-web") == ["127.0.0.1:3000:3000"] and
    published("admin-web") == ["127.0.0.1:3001:3000"] and
    published("reseller-web") == ["127.0.0.1:3002:3000"] and
    no_ports("postgres") and
    no_ports("redis") and
    no_ports("worker") and
    no_ports("telegram-bot") and
    no_unsafe_hosts and
    no_duplicates
  ' <<<"$config_json" >/dev/null || fail "test-server Compose port isolation check failed"
}

resolve_env_file "$@"
env_file="$resolved_env_file"
export VPN_SALE_TEST_SERVER_ENV_FILE="$env_file"

log "Rendering test-server Compose configuration"
config_json="$(docker compose \
  -f "$repo_root/docker-compose.yml" \
  -f "$repo_root/docker-compose.test-server.yml" \
  --env-file "$env_file" \
  --profile telegram \
  --profile web \
  --profile ops \
  config --format json)"
assert_ports "$config_json"
log "Test-server Compose verification passed"
