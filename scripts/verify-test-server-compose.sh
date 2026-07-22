#!/usr/bin/env bash
set -euo pipefail

log() { printf '==> %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

xtrace_was_enabled() { [[ $- == *x* ]]; }

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
  CONFIG_JSON="$config_json" python3 - <<'PYVALIDATOR'
import json
import os
import sys
from collections import Counter

expected = {
    "api": [("127.0.0.1", "8000", "8000", "tcp")],
    "customer-web": [("127.0.0.1", "3000", "3000", "tcp")],
    "admin-web": [("127.0.0.1", "3001", "3000", "tcp")],
    "reseller-web": [("127.0.0.1", "3002", "3000", "tcp")],
    "postgres": [],
    "redis": [],
    "worker": [],
    "telegram-bot": [],
}


def norm(value):
    if value is None:
        return ""
    return str(value)


def binding_tuple(port):
    return (
        norm(port.get("host_ip")),
        norm(port.get("published")),
        norm(port.get("target")),
        norm(port.get("protocol") or "tcp"),
    )


def format_binding(binding):
    host_ip, published, target, protocol = binding
    host = host_ip if host_ip else "<all-interfaces>"
    return f"{host}:{published}->{target}/{protocol}"


def format_bindings(bindings):
    if not bindings:
        return "<none>"
    return ", ".join(format_binding(binding) for binding in sorted(bindings))

model = json.loads(os.environ["CONFIG_JSON"])
services = model.get("services") or {}
errors = []

for service, expected_bindings in expected.items():
    if service not in services:
        errors.append(f"missing service: {service}")
        continue
    actual = [binding_tuple(port) for port in (services[service].get("ports") or [])]
    expected_sorted = sorted(expected_bindings)
    actual_sorted = sorted(actual)
    if actual_sorted != expected_sorted:
        errors.append(f"service {service} expected: {format_bindings(expected_sorted)}")
        errors.append(f"service {service} actual:   {format_bindings(actual_sorted)}")
        for binding in sorted(set(expected_sorted) - set(actual_sorted)):
            errors.append(f"service {service} missing binding: {format_binding(binding)}")
        for binding in sorted(set(actual_sorted) - set(expected_sorted)):
            errors.append(f"service {service} unexpected binding: {format_binding(binding)}")

all_bindings = []
for service, definition in sorted(services.items()):
    ports = [binding_tuple(port) for port in (definition.get("ports") or [])]
    if service not in expected and ports:
        errors.append(f"unexpected service with ports: {service} actual: {format_bindings(ports)}")
    for binding in ports:
        all_bindings.append((service, binding))
        host_ip = binding[0]
        if host_ip in {"", "0.0.0.0", "::"}:
            errors.append(f"service {service} unsafe host IP: {format_binding(binding)}")

binding_counts = Counter(binding for _, binding in all_bindings)
for binding, count in sorted(binding_counts.items()):
    if count > 1:
        services_with_binding = sorted(service for service, candidate in all_bindings if candidate == binding)
        errors.append(
            f"duplicate binding: {format_binding(binding)} used by {', '.join(services_with_binding)}"
        )

if errors:
    for error in errors:
        print(error, file=sys.stderr)
    sys.exit(1)
PYVALIDATOR
}


assert_database_urls() {
  local config_json="$1"
  local env_file="$2"
  CONFIG_JSON="$config_json" ENV_FILE="$env_file" python3 - <<'PYVALIDATOR'
import json
import os
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

SENSITIVE_NAMES = {"POSTGRES_PASSWORD", "DATABASE_URL", "VPN_SALE_DATABASE_URL", "VPN_SALE_SYNC_DATABASE_URL"}
DEV_SENTINEL = "vpnsale_" + "dev_" + "password"


def read_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def service_environment(service: dict) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, dict):
        return {str(key): "" if value is None else str(value) for key, value in env.items()}
    result: dict[str, str] = {}
    for item in env:
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def parse_db_url(name: str, value: str):
    parsed = urlparse(value)
    return {
        "name": name,
        "scheme": parsed.scheme,
        "username": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "hostname": parsed.hostname or "",
        "database": (parsed.path or "").lstrip("/"),
    }

runtime = read_env(os.environ["ENV_FILE"])
model = json.loads(os.environ["CONFIG_JSON"])
api_env = service_environment((model.get("services") or {}).get("api") or {})
errors: list[str] = []

for key in ["POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "DATABASE_URL", "VPN_SALE_DATABASE_URL", "VPN_SALE_SYNC_DATABASE_URL"]:
    if not runtime.get(key):
        errors.append(f"runtime env missing {key}")

for key in ["DATABASE_URL", "VPN_SALE_DATABASE_URL", "VPN_SALE_SYNC_DATABASE_URL"]:
    if key not in api_env:
        errors.append(f"api environment missing {key}")
    elif runtime.get(key) != api_env[key]:
        errors.append(f"api environment {key} does not match runtime env file")
    if DEV_SENTINEL in api_env.get(key, ""):
        errors.append(f"api environment {key} contains development password")

postgres_password = runtime.get("POSTGRES_PASSWORD", "")
postgres_user = runtime.get("POSTGRES_USER", "")
postgres_db = runtime.get("POSTGRES_DB", "")

expected_schemes = {
    "DATABASE_URL": "postgresql+asyncpg",
    "VPN_SALE_DATABASE_URL": "postgresql+asyncpg",
    "VPN_SALE_SYNC_DATABASE_URL": "postgresql",
}

for key, expected_scheme in expected_schemes.items():
    value = api_env.get(key) or runtime.get(key) or ""
    parsed = parse_db_url(key, value)
    if parsed["scheme"] != expected_scheme:
        errors.append(f"{key} uses unexpected PostgreSQL driver")
    if parsed["password"] != postgres_password:
        errors.append(f"{key} password does not match POSTGRES_PASSWORD")
    if parsed["hostname"] != "postgres":
        errors.append(f"{key} host is not postgres")
    if parsed["username"] != postgres_user:
        errors.append(f"{key} user does not match POSTGRES_USER")
    if parsed["database"] != postgres_db:
        errors.append(f"{key} database does not match POSTGRES_DB")

if errors:
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)
    sys.exit(1)
print("PASS: database URL variables match runtime env file and decode to POSTGRES_PASSWORD")
PYVALIDATOR
}

resolve_env_file "$@"
env_file="$resolved_env_file"
export VPN_SALE_TEST_SERVER_ENV_FILE="$env_file"

log "Rendering test-server Compose configuration"
restore_xtrace=false
if xtrace_was_enabled; then
  restore_xtrace=true
  set +x
fi
config_json="$("$repo_root/scripts/vpn-sale-compose-test-server" --env-file "$env_file" \
  --profile telegram \
  --profile web \
  --profile ops \
  config --format json)"
assert_ports "$config_json" || fail "test-server Compose port isolation check failed"
assert_database_urls "$config_json" "$env_file" || fail "test-server Compose database URL consistency check failed"
if [[ "$restore_xtrace" == true ]]; then
  set -x
fi
log "Test-server Compose verification passed"
