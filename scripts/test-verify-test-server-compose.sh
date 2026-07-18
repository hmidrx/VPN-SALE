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
case "${FAKE_PORT_MODE:-safe}" in
  safe)
    cat <<'JSON'
{"services":{"api":{"ports":[{"host_ip":"127.0.0.1","published":"8000","target":8000}]},"customer-web":{"ports":[{"host_ip":"127.0.0.1","published":"3000","target":3000}]},"admin-web":{"ports":[{"host_ip":"127.0.0.1","published":"3001","target":3000}]},"reseller-web":{"ports":[{"host_ip":"127.0.0.1","published":"3002","target":3000}]},"postgres":{},"redis":{},"worker":{},"telegram-bot":{}}}
JSON
    ;;
  unsafe)
    cat <<'JSON'
{"services":{"api":{"ports":[{"host_ip":"0.0.0.0","published":"8000","target":8000}]},"customer-web":{"ports":[{"host_ip":"127.0.0.1","published":"3000","target":3000}]},"admin-web":{"ports":[{"host_ip":"127.0.0.1","published":"3001","target":3000}]},"reseller-web":{"ports":[{"host_ip":"127.0.0.1","published":"3002","target":3000}]},"postgres":{"ports":[{"host_ip":"127.0.0.1","published":"5432","target":5432}]},"redis":{},"worker":{},"telegram-bot":{}}}
JSON
    ;;
  *) echo "unknown FAKE_PORT_MODE" >&2; exit 4 ;;
esac
DOCKER
chmod +x "$fake_bin/docker"
export PATH="$fake_bin:$PATH"

run_dir="$tmp_root/run"
mkdir -p "$run_dir"
cp "$template" "$tmp_root/template.before"
stdout="$tmp_root/stdout"
stderr="$tmp_root/stderr"
TMPDIR="$run_dir" "$script" >"$stdout" 2>"$stderr"
if find "$run_dir" -mindepth 1 -print -quit | grep -q .; then
  echo "temporary env directory was not cleaned up" >&2
  exit 1
fi
cmp -s "$template" "$tmp_root/template.before" || { echo "tracked example changed" >&2; exit 1; }

explicit_env="$tmp_root/explicit.env"
cp "$template" "$explicit_env"
printf '\nUNIQUE_TEST_SECRET_VALUE=do-not-print-this-value\n' >>"$explicit_env"
"$script" "$explicit_env" >"$stdout" 2>"$stderr"
if grep -F "do-not-print-this-value" "$stdout" "$stderr" >/dev/null; then
  echo "verification printed an environment value" >&2
  exit 1
fi

missing_env="$tmp_root/missing.env"
if "$script" "$missing_env" >"$stdout" 2>"$stderr"; then
  echo "missing explicit env file unexpectedly passed" >&2
  exit 1
fi
grep -F "test-server env file does not exist" "$stderr" >/dev/null

FAKE_PORT_MODE=unsafe "$script" "$explicit_env" >"$stdout" 2>"$stderr" && {
  echo "unsafe public-port configuration unexpectedly passed" >&2
  exit 1
}
grep -F "port isolation check failed" "$stderr" >/dev/null

FAKE_PORT_MODE=safe "$script" "$explicit_env" >"$stdout" 2>"$stderr"

echo "verify-test-server-compose regression tests passed"
