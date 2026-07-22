#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
script="$repo_root/scripts/verify-test-server-compose.sh"
template="$repo_root/infra/deployment/env/test-server.env.example"
tmp_root="$(mktemp -d)"
cleanup() { rm -rf "$tmp_root"; }
trap cleanup EXIT

fake_bin="$tmp_root/bin"
mkdir -p "$fake_bin"
cat >"$fake_bin/docker" <<'DOCKER'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" != "compose" ]]; then
  echo "unexpected docker command" >&2
  exit 2
fi
env_file=""
for ((i=1; i <= $#; i++)); do
  arg="${!i}"
  if [[ "$arg" == "/opt/vpn-sale-runtime/test.env" ]]; then
    echo "VPS runtime path must not be required by verification" >&2
    exit 3
  fi
  if [[ "$arg" == "--env-file" ]]; then
    next=$((i + 1))
    env_file="${!next}"
  fi
done
[[ -n "$env_file" ]] || { echo "missing --env-file" >&2; exit 4; }
[[ "${VPN_SALE_TEST_SERVER_ENV_FILE:-}" == "$env_file" ]] || { echo "wrapper did not align env_file interpolation" >&2; exit 5; }
FAKE_DOCKER_ENV_FILE="$env_file" python3 - <<'PY'
import json
import os
from pathlib import Path

def read_env(path):
    values = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values

api_env = {key: value for key, value in read_env(os.environ["FAKE_DOCKER_ENV_FILE"]).items() if key in {"DATABASE_URL", "VPN_SALE_DATABASE_URL", "VPN_SALE_SYNC_DATABASE_URL"}}
case = Path(os.environ["FAKE_DOCKER_ENV_FILE"]).name.removesuffix(".env")
known_cases = {"db-mismatch", "dev-password", "different-order", "numeric-ports", "missing-host-ip", "all-interface-ipv4", "all-interface-ipv6", "public-postgres", "public-redis", "duplicate-public-localhost", "unexpected-reverse-proxy", "missing-service"}
if case not in known_cases:
    case = "safe"
if case == "db-mismatch":
    api_env["VPN_SALE_DATABASE_URL"] = "postgresql+asyncpg://" + "vpnsale:wrong%40" + "password@postgres:5432/vpnsale"
elif case == "dev-password":
    api_env["VPN_SALE_DATABASE_URL"] = "postgresql+asyncpg://" + "vpnsale:vpnsale_" + "dev_" + "password@postgres:5432/vpnsale"

safe_services = {
    "api": {"environment": api_env, "ports": [{"host_ip": "127.0.0.1", "published": "8000", "target": 8000}]},
    "customer-web": {"ports": [{"host_ip": "127.0.0.1", "published": "3000", "target": 3000}]},
    "admin-web": {"ports": [{"host_ip": "127.0.0.1", "published": "3001", "target": 3000}]},
    "reseller-web": {"ports": [{"host_ip": "127.0.0.1", "published": "3002", "target": 3000}]},
    "postgres": {},
    "redis": {},
    "worker": {},
    "telegram-bot": {},
    "reverse-proxy": {"profiles": ["disabled-in-test-server"]},
}
services = json.loads(json.dumps(safe_services))

if case in {"safe", "db-mismatch", "dev-password"}:
    pass
elif case == "different-order":
    services = {name: services[name] for name in ["telegram-bot", "worker", "redis", "postgres", "reseller-web", "admin-web", "customer-web", "api", "reverse-proxy"]}
elif case == "numeric-ports":
    for definition in services.values():
        for port in definition.get("ports", []):
            port["published"] = int(port["published"])
            port["target"] = int(port["target"])
elif case == "missing-host-ip":
    services["api"]["ports"][0].pop("host_ip")
elif case == "all-interface-ipv4":
    services["api"]["ports"][0]["host_ip"] = "0.0.0.0"
elif case == "all-interface-ipv6":
    services["api"]["ports"][0]["host_ip"] = "::"
elif case == "public-postgres":
    services["postgres"] = {"ports": [{"host_ip": "127.0.0.1", "published": "5432", "target": 5432}]}
elif case == "public-redis":
    services["redis"] = {"ports": [{"host_ip": "127.0.0.1", "published": "6379", "target": 6379}]}
elif case == "duplicate-public-localhost":
    services["api"]["ports"].append({"host_ip": "0.0.0.0", "published": "8000", "target": 8000})
elif case == "unexpected-reverse-proxy":
    services["reverse-proxy"] = {"ports": [{"host_ip": "127.0.0.1", "published": "8080", "target": 80}]}
elif case == "missing-service":
    del services["telegram-bot"]
else:
    raise SystemExit(f"unknown FAKE_CASE: {case}")

print(json.dumps({"services": services}, sort_keys=False))
PY
DOCKER
chmod +x "$fake_bin/docker"
export PATH="$fake_bin:$PATH"

run_script() {
  local case_name="$1"
  local env_file="${2:-}"
  stdout="$tmp_root/stdout-$case_name"
  stderr="$tmp_root/stderr-$case_name"
  if [[ -n "$env_file" ]]; then
    local case_env="$tmp_root/$case_name.env"
    cp "$env_file" "$case_env"
    "$script" "$case_env" >"$stdout" 2>"$stderr"
  else
    "$script" >"$stdout" 2>"$stderr"
  fi
}

expect_pass() {
  local case_name="$1"
  run_script "$case_name" "$explicit_env"
}

expect_fail() {
  local case_name="$1"
  local expected_message="$2"
  if run_script "$case_name" "$explicit_env"; then
    echo "$case_name unexpectedly passed" >&2
    exit 1
  fi
  grep -F "$expected_message" "$stderr" >/dev/null || {
    echo "$case_name did not report expected diagnostic: $expected_message" >&2
    cat "$stderr" >&2
    exit 1
  }
}

run_dir="$tmp_root/run"
mkdir -p "$run_dir"
cp "$template" "$tmp_root/template.before"
stdout="$tmp_root/stdout-clean"
stderr="$tmp_root/stderr-clean"
TMPDIR="$run_dir" "$script" >"$stdout" 2>"$stderr"
if find "$run_dir" -mindepth 1 -print -quit | grep -q .; then
  echo "temporary env directory was not cleaned up" >&2
  exit 1
fi
cmp -s "$template" "$tmp_root/template.before" || { echo "tracked example changed" >&2; exit 1; }

make_env() {
  local target="$1"
  local pg_secret
  pg_secret="pa@@ss:word/with?chars#and%$(printf percent)"
  python3 - "$target" "$pg_secret" <<'PY'
import sys
from pathlib import Path
from urllib.parse import quote
path = Path(sys.argv[1])
pg_secret = sys.argv[2]
user = "vpnsale"
db = "vpnsale"
encoded = quote(pg_secret, safe="")
path.write_text("\n".join([
    f"POSTGRES_USER={user}",
    f"POSTGRES_DB={db}",
    f"POSTGRES_PASSWORD={pg_secret}",
    "DATABASE_URL=" + "postgresql+asyncpg://" + f"{user}:{encoded}@postgres:5432/{db}",
    "VPN_SALE_DATABASE_URL=" + "postgresql+asyncpg://" + f"{user}:{encoded}@postgres:5432/{db}",
    "VPN_SALE_SYNC_DATABASE_URL=" + "postgresql://" + f"{user}:{encoded}@postgres:5432/{db}",
    "VPN_SALE_API_PUBLIC_ORIGIN=https://api.example.test",
    "VPN_SALE_CUSTOMER_API_FRONTEND_URL=https://api.example.test",
    "VPN_SALE_TELEGRAM_BOT_USERNAME=disabled_bot",
    "VPN_SALE_TELEGRAM_BOT_TOKEN=example-token",
    "VPN_SALE_IDENTITY_ENCRYPTION_KEY=example",
    "VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY=example",
    "VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY=example",
    "VPN_SALE_ADMIN_CSRF_SECRET=example",
    "VPN_SALE_CUSTOMER_CSRF_SECRET=example",
    "VPN_SALE_TELEGRAM_RATE_LIMIT_KEY=example",
    "",
]))
PY
}

explicit_env="$tmp_root/explicit.env"
make_env "$explicit_env"
printf '\nUNIQUE_TEST_SECRET_VALUE=do-not-print-this-value\n' >>"$explicit_env"
expect_pass safe
if grep -F "do-not-print-this-value" "$stdout" "$stderr" >/dev/null; then
  echo "verification printed an environment value" >&2
  exit 1
fi

missing_env="$tmp_root/missing.env"
stdout="$tmp_root/stdout-missing-env"
stderr="$tmp_root/stderr-missing-env"
if "$script" "$missing_env" >"$stdout" 2>"$stderr"; then
  echo "missing explicit env file unexpectedly passed" >&2
  exit 1
fi
grep -F "test-server env file does not exist" "$stderr" >/dev/null

expect_pass different-order
expect_pass numeric-ports
expect_fail missing-host-ip "unsafe host IP"
expect_fail all-interface-ipv4 "unsafe host IP"
expect_fail all-interface-ipv6 "unsafe host IP"
expect_fail public-postgres "service postgres unexpected binding"
expect_fail public-redis "service redis unexpected binding"
expect_fail duplicate-public-localhost "unsafe host IP"
expect_fail unexpected-reverse-proxy "unexpected service with ports: reverse-proxy"
expect_fail missing-service "missing service: telegram-bot"
expect_fail db-mismatch "VPN_SALE_DATABASE_URL password does not match POSTGRES_PASSWORD"
expect_fail dev-password "contains development password"
if grep -F 'pa@@ss' "$tmp_root"/stdout-* "$tmp_root"/stderr-* >/dev/null 2>&1; then
  echo "verification printed a raw password" >&2
  exit 1
fi
if grep -F 'postgresql://' "$tmp_root"/stdout-* "$tmp_root"/stderr-* >/dev/null 2>&1 || grep -F 'postgresql+asyncpg://' "$tmp_root"/stdout-* "$tmp_root"/stderr-* >/dev/null 2>&1; then
  echo "verification printed a database URL" >&2
  exit 1
fi

custom_env="$tmp_root/custom.env"
make_env "$custom_env"
DATABASE_URL=hostile VPN_SALE_DATABASE_URL=hostile VPN_SALE_SYNC_DATABASE_URL=hostile expect_pass safe

echo "verify-test-server-compose regression tests passed"
