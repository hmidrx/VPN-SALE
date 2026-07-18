#!/usr/bin/env bash
set -Eeuo pipefail

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }; }
need_cmd docker
need_cmd python3

compose_version="$(docker compose version --short 2>/dev/null | sed -E 's/^v//; s/[ +].*$//')"
python3 - "$compose_version" <<'PY'
import sys

raw = sys.argv[1]
try:
    current = tuple(int(part) for part in raw.split(".")[:3])
except ValueError:
    raise SystemExit(f"Could not parse Docker Compose version: {raw!r}") from None
required = (2, 24, 4)
if len(current) < 3:
    current = current + (0,) * (3 - len(current))
if current < required:
    raise SystemExit("Docker Compose 2.24.4 or newer is required for !override port replacement")
PY

example_env="infra/deployment/env/test-server.env.example"
if [[ ! -f "$example_env" ]]; then
  echo "Missing sanitized test-server environment example." >&2
  exit 1
fi

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT
safe_env="$tmpdir/test.env"

python3 - "$example_env" "$safe_env" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
replacements = {
    "POSTGRES_PASSWORD": "safe-postgres-placeholder",
    "VPN_SALE_DATABASE_URL": "postgresql+asyncpg://vpnsale_test:safe-postgres-placeholder@postgres:5432/vpnsale_test",
    "VPN_SALE_IDENTITY_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
    "VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY": "safe-admin-signing-placeholder",
    "VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY": "safe-customer-signing-placeholder",
    "VPN_SALE_ADMIN_CSRF_SECRET": "safe-admin-csrf-placeholder",
    "VPN_SALE_CUSTOMER_CSRF_SECRET": "safe-customer-csrf-placeholder",
    "VPN_SALE_TELEGRAM_BOT_USERNAME": "safe_test_bot",
    "VPN_SALE_TELEGRAM_BOT_TOKEN": "",
    "VPN_SALE_TELEGRAM_RATE_LIMIT_KEY": "safe-bot-rate-limit-placeholder",
}
lines = []
seen: set[str] = set()
for raw in source.read_text().splitlines():
    if not raw or raw.startswith("#") or "=" not in raw:
        lines.append(raw)
        continue
    key, _value = raw.split("=", 1)
    if key in replacements:
        lines.append(f"{key}={replacements[key]}")
        seen.add(key)
    else:
        lines.append(raw)
for key, value in replacements.items():
    if key not in seen:
        lines.append(f"{key}={value}")
target.write_text("\n".join(lines) + "\n")
PY

config_json="$tmpdir/docker-compose.test-server.json"
docker compose \
  --env-file "$safe_env" \
  -f docker-compose.yml \
  -f docker-compose.test-server.yml \
  --profile ops \
  --profile web \
  --profile telegram \
  config --format json >"$config_json"

python3 - "$config_json" <<'PY'
import json
import sys
from collections import Counter
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text())
services = config.get("services", {})
expected = {
    "api": [("127.0.0.1", 8000, 8000)],
    "customer-web": [("127.0.0.1", 3000, 3000)],
    "admin-web": [("127.0.0.1", 3001, 3000)],
    "reseller-web": [("127.0.0.1", 3002, 3000)],
}
no_ports = {"postgres", "redis", "worker", "telegram-bot"}
unsafe_host_ips = {"", "0.0.0.0", "::"}
observed_published: list[tuple[str, int]] = []

def normalize(service: str) -> list[tuple[str, int, int]]:
    ports = services.get(service, {}).get("ports") or []
    bindings = []
    for entry in ports:
        host_ip = str(entry.get("host_ip", ""))
        published_raw = entry.get("published")
        target_raw = entry.get("target")
        if host_ip in unsafe_host_ips:
            raise SystemExit(f"{service} has unsafe or missing host_ip in rendered ports")
        try:
            published = int(published_raw)
            target = int(target_raw)
        except (TypeError, ValueError):
            raise SystemExit(f"{service} has non-numeric rendered port binding") from None
        observed_published.append((host_ip, published))
        bindings.append((host_ip, published, target))
    return bindings

for service, expected_bindings in expected.items():
    if service not in services:
        raise SystemExit(f"missing expected service: {service}")
    actual = normalize(service)
    if actual != expected_bindings:
        raise SystemExit(f"{service} rendered ports {actual!r}, expected {expected_bindings!r}")

for service in no_ports:
    if service not in services:
        raise SystemExit(f"missing expected service: {service}")
    actual = normalize(service)
    if actual:
        raise SystemExit(f"{service} must not publish host ports")

allowed_with_ports = set(expected)
for service in sorted(services):
    if service in allowed_with_ports or service in no_ports:
        continue
    actual = normalize(service)
    if actual:
        raise SystemExit(f"{service} has unexpected test-server host ports")

duplicates = [binding for binding, count in Counter(observed_published).items() if count > 1]
if duplicates:
    raise SystemExit("duplicate published test-server host ports detected")

print("Test-server Compose port isolation verified.")
PY
