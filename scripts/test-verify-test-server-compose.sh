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
for arg in "$@"; do
  if [[ "$arg" == "/opt/vpn-sale-runtime/test.env" ]]; then
    echo "VPS runtime path must not be required by verification" >&2
    exit 3
  fi
done
python3 - <<'PY'
import json
import os

safe_services = {
    "api": {"ports": [{"host_ip": "127.0.0.1", "published": "8000", "target": 8000}]},
    "customer-web": {"ports": [{"host_ip": "127.0.0.1", "published": "3000", "target": 3000}]},
    "admin-web": {"ports": [{"host_ip": "127.0.0.1", "published": "3001", "target": 3000}]},
    "reseller-web": {"ports": [{"host_ip": "127.0.0.1", "published": "3002", "target": 3000}]},
    "postgres": {},
    "redis": {},
    "worker": {},
    "telegram-bot": {},
    "reverse-proxy": {"profiles": ["disabled-in-test-server"]},
}
case = os.environ.get("FAKE_CASE", "safe")
services = json.loads(json.dumps(safe_services))

if case == "safe":
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
    FAKE_CASE="$case_name" "$script" "$env_file" >"$stdout" 2>"$stderr"
  else
    FAKE_CASE="$case_name" "$script" >"$stdout" 2>"$stderr"
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
TMPDIR="$run_dir" FAKE_CASE=safe "$script" >"$stdout" 2>"$stderr"
if find "$run_dir" -mindepth 1 -print -quit | grep -q .; then
  echo "temporary env directory was not cleaned up" >&2
  exit 1
fi
cmp -s "$template" "$tmp_root/template.before" || { echo "tracked example changed" >&2; exit 1; }

explicit_env="$tmp_root/explicit.env"
cp "$template" "$explicit_env"
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

echo "verify-test-server-compose regression tests passed"
