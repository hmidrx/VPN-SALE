#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
root_test_dirs=()
cleanup() {
  local status=$? cleanup_status=0
  trap - EXIT INT TERM
  set +e
  rm -rf "$tmp" || cleanup_status=1
  if ((${#root_test_dirs[@]})); then sudo rm -rf -- "${root_test_dirs[@]}" || cleanup_status=1; fi
  if ((status == 0 && cleanup_status != 0)); then status=$cleanup_status; fi
  exit "$status"
}
trap cleanup EXIT INT TERM
contains(){ grep -Eq -- "$1" "$2"; }

# A restrictive checkout whose final tracked file is non-executable must normalize successfully.
git init -q "$tmp/permissions"; git -C "$tmp/permissions" config user.email test@example.invalid; git -C "$tmp/permissions" config user.name Test
mkdir -p "$tmp/permissions/z"; printf a >"$tmp/permissions/a"; printf z >"$tmp/permissions/z/last"; git -C "$tmp/permissions" add .; git -C "$tmp/permissions" commit -qm base
chmod -R u=rwX,go= "$tmp/permissions"
# shellcheck source=scripts/test-server-installer-lib.sh disable=SC1091
source "$repo_root/scripts/test-server-installer-lib.sh"
normalize_checkout_permissions "$tmp/permissions"
[[ $(stat -c %a "$tmp/permissions/a") == 644 && $(stat -c %a "$tmp/permissions/z") == 755 ]]

write_state "$tmp/state.json" checkout TEST example.test repo main 0123456789abcdef vpn-sale
jq -e '.last_completed_phase == "checkout" and .selected_ref == "main" and .selected_commit == "0123456789abcdef"' "$tmp/state.json" >/dev/null
write_state "$tmp/state.json" build TEST example.test repo main 0123456789abcdef vpn-sale
jq -e '.last_completed_phase == "build"' "$tmp/state.json" >/dev/null
[[ $(stat -c %a "$tmp/state.json") == 600 ]]

# Build a local remote whose installer proves repository-relative helper discovery.
git init -q "$tmp/source"; git -C "$tmp/source" config user.email test@example.invalid; git -C "$tmp/source" config user.name Test
mkdir -p "$tmp/source/scripts"; printf 'fixture helper\n' >"$tmp/source/scripts/test-server-installer-lib.sh"
cat >"$tmp/source/scripts/install-test-server.sh" <<'INNER'
#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test -f "$root/scripts/test-server-installer-lib.sh"
printf '%s\n' "$@" >"${BOOTSTRAP_CAPTURE:?}"
[[ "${BOOTSTRAP_FORCE_FAILURE:-false}" != true ]]
INNER
chmod +x "$tmp/source/scripts/install-test-server.sh"; git -C "$tmp/source" add .; git -C "$tmp/source" commit -qm base; git -C "$tmp/source" branch -M main
expected="$(git -C "$tmp/source" rev-parse HEAD)"

run_bootstrap_case() {
  local name="$1" should_fail="$2" root_dir capture
  root_dir="/tmp/vpn-sale-bootstrap-${name}-$$"; capture="$tmp/${name}.capture"
  root_test_dirs+=("$root_dir")
  sudo install -d -m 0700 "$root_dir"
  if [[ "$should_fail" == true ]]; then
    if sudo env BOOTSTRAP_CAPTURE="$root_dir/capture" BOOTSTRAP_FORCE_FAILURE=true "$repo_root/scripts/bootstrap-test-server.sh" --repo "$tmp/source" --ref main --install-dir "$root_dir/install" -- --domain example.test; then
      echo 'intentionally failed bootstrap unexpectedly succeeded' >&2; return 1
    fi
  else
    sudo env BOOTSTRAP_CAPTURE="$root_dir/capture" "$repo_root/scripts/bootstrap-test-server.sh" --repo "$tmp/source" --ref main --install-dir "$root_dir/install" -- --domain example.test
    sudo cat "$root_dir/capture" | tee "$capture" >/dev/null
    contains '^--expected-commit$' "$capture"; contains "^${expected}$" "$capture"; contains '^--domain$' "$capture"
  fi
  sudo rm -rf "$root_dir"
  [[ ! -e "$root_dir" ]]
}
run_bootstrap_case success false
run_bootstrap_case intentional-failure true
# Normal-user cleanup remains possible after both sudo cases.
probe="$tmp/user-cleanup"; mkdir "$probe"; rm -rf "$probe"; [[ ! -e "$probe" ]]

if sudo "$repo_root/scripts/reset-disposable-test-server.sh" >/dev/null 2>&1; then echo 'unconfirmed reset succeeded' >&2; exit 1; fi
sudo "$repo_root/scripts/reset-disposable-test-server.sh" --dry-run | tee "$tmp/reset" >/dev/null
contains '/opt/vpn-sale /opt/vpn-sale-runtime' "$tmp/reset"
contains 'test_server_postgres_data.*test_server_redis_data' "$repo_root/scripts/reset-disposable-test-server.sh"
if grep -En 'docker (system|network|container|image) prune|/etc/ssh|/swapfile|apt/sources|down -v' "$repo_root/scripts/reset-disposable-test-server.sh"; then exit 1; fi
printf 'test-server lifecycle regressions passed\n'
