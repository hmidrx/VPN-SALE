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

resolve_env_file "$@"
env_file="$resolved_env_file"
export VPN_SALE_TEST_SERVER_ENV_FILE="$env_file"

log "Rendering test-server Compose configuration"
restore_xtrace=false
if xtrace_was_enabled; then
  restore_xtrace=true
  set +x
fi
config_json="$(docker compose \
  -f "$repo_root/docker-compose.yml" \
  -f "$repo_root/docker-compose.test-server.yml" \
  --env-file "$env_file" \
  --profile telegram \
  --profile web \
  --profile ops \
  config --format json)"
assert_ports "$config_json" || fail "test-server Compose port isolation check failed"
if [[ "$restore_xtrace" == true ]]; then
  set -x
fi
log "Test-server Compose verification passed"
