#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
# Regression: restrictive tracked permissions and a non-executable last file do not trip set -e.
git init -q "$tmp/permissions"; git -C "$tmp/permissions" config user.email test@example.invalid; git -C "$tmp/permissions" config user.name Test
mkdir -p "$tmp/permissions/z"; printf a >"$tmp/permissions/a"; printf z >"$tmp/permissions/z/last"; git -C "$tmp/permissions" add .; git -C "$tmp/permissions" commit -qm base
chmod -R u=rwX,go= "$tmp/permissions"
# shellcheck source=scripts/test-server-installer-lib.sh
source "$repo_root/scripts/test-server-installer-lib.sh"
normalize_checkout_permissions "$tmp/permissions"
[[ $(stat -c %a "$tmp/permissions/a") == 644 && $(stat -c %a "$tmp/permissions/z") == 755 ]]
# Atomic resumable checkpoints preserve selected ref/commit and advance only after completion.
write_state "$tmp/state.json" checkout TEST example.test repo main 0123456789abcdef vpn-sale
jq -e '.last_completed_phase == "checkout" and .selected_ref == "main" and .selected_commit == "0123456789abcdef"' "$tmp/state.json" >/dev/null
write_state "$tmp/state.json" build TEST example.test repo main 0123456789abcdef vpn-sale
jq -e '.last_completed_phase == "build"' "$tmp/state.json" >/dev/null
[[ $(stat -c %a "$tmp/state.json") == 600 ]]
# Standalone bootstrap obtains the whole repository, checks out an exact commit, and finds its installer.
git init -q "$tmp/source"; git -C "$tmp/source" config user.email test@example.invalid; git -C "$tmp/source" config user.name Test; mkdir -p "$tmp/source/scripts"
cat >"$tmp/source/scripts/install-test-server.sh" <<'INNER'
#!/usr/bin/env bash
printf '%s\n' "$@" >"${BOOTSTRAP_CAPTURE:?}"
INNER
chmod +x "$tmp/source/scripts/install-test-server.sh"; git -C "$tmp/source" add .; git -C "$tmp/source" commit -qm base; git -C "$tmp/source" branch -M main
BOOTSTRAP_CAPTURE="$tmp/capture" sudo -E "$repo_root/scripts/bootstrap-test-server.sh" --repo "$tmp/source" --ref main --install-dir "$tmp/install" -- --domain example.test
expected="$(git -C "$tmp/source" rev-parse HEAD)"; grep -Fx -- "$expected" "$tmp/capture" >/dev/null; grep -Fx -- '--expected-commit' "$tmp/capture" >/dev/null; grep -Fx -- '--domain' "$tmp/capture" >/dev/null
# Reset must be explicit and may name only exact TEST resources/managed paths.
if sudo "$repo_root/scripts/reset-disposable-test-server.sh" >/dev/null 2>&1; then echo 'unconfirmed reset succeeded' >&2; exit 1; fi
sudo "$repo_root/scripts/reset-disposable-test-server.sh" --dry-run | tee "$tmp/reset" >/dev/null
grep -F '/opt/vpn-sale /opt/vpn-sale-runtime' "$tmp/reset" >/dev/null
rg -q 'test_server_postgres_data.*test_server_redis_data' "$repo_root/scripts/reset-disposable-test-server.sh"
if rg -n 'docker (system|network|container|image) prune|/etc/ssh|/swapfile|apt/sources|down -v' "$repo_root/scripts/reset-disposable-test-server.sh"; then exit 1; fi
printf 'test-server lifecycle regressions passed\n'
