#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-installer-lib.sh
source "$repo_root/scripts/test-server-installer-lib.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fakebin="$tmp/bin"; mkdir -p "$fakebin"
export PATH="$fakebin:$PATH"
export CADDY_CONFIG_DIR="$tmp/etc/caddy"
mkdir -p "$CADDY_CONFIG_DIR"
log="$tmp/calls.log"

cat >"$fakebin/caddy" <<'FAKE'
#!/usr/bin/env bash
printf 'caddy %q %q %q %q\n' "${1:-}" "${2:-}" "${3:-}" "${4:-}" >>"$CALL_LOG"
[[ "${CADDY_VALIDATE_FAIL:-false}" != true ]]
FAKE
cat >"$fakebin/systemctl" <<'FAKE'
#!/usr/bin/env bash
printf 'systemctl %q %q %q\n' "${1:-}" "${2:-}" "${3:-}" >>"$CALL_LOG"
if [[ "${1:-}" == restart && "${SYSTEMCTL_RESTART_FAIL:-false}" == true ]]; then exit 1; fi
exit 0
FAKE
chmod +x "$fakebin/caddy" "$fakebin/systemctl"
export CALL_LOG="$log"

assert(){ "$@" || { echo "assertion failed: $*" >&2; exit 1; }; }
assert_not_exists(){ [[ ! -e "$1" ]] || { echo "unexpected file exists: $1" >&2; exit 1; }; }

rendered="$tmp/tmp.generic-name"
render_managed_caddyfile dr-ping.com >"$rendered"
[[ "$(head -n1 "$rendered")" == '# vpn-sale-test-server-managed' ]]
if grep -Fq 'fast.dr-ping.com' "$rendered"; then echo 'forbidden hostname rendered' >&2; exit 1; fi
for host in app.dr-ping.com api.dr-ping.com admin.dr-ping.com reseller.dr-ping.com; do grep -Fq "$host" "$rendered"; done

marker="$tmp/runtime/caddy-managed.sha256"
activate_managed_caddyfile "$rendered" "$marker"
grep -Fq 'caddy validate --adapter caddyfile --config' "$log"
assert test -s "$marker"
assert cmp -s "$rendered" "$CADDY_CONFIG_DIR/Caddyfile"

rm -f "$marker" "$log" "$CADDY_CONFIG_DIR/Caddyfile"
CADDY_VALIDATE_FAIL=true activate_managed_caddyfile "$rendered" "$marker" 2>/dev/null && { echo 'validation failure activated' >&2; exit 1; }
assert_not_exists "$CADDY_CONFIG_DIR/Caddyfile"
assert_not_exists "$marker"
unset CADDY_VALIDATE_FAIL

printf '# vpn-sale-test-server-managed\n:80 {\n  respond "old"\n}\n' >"$CADDY_CONFIG_DIR/Caddyfile"
old_hash="$(sha256sum "$CADDY_CONFIG_DIR/Caddyfile" | awk '{print $1}')"
SYSTEMCTL_RESTART_FAIL=true activate_managed_caddyfile "$rendered" "$marker" 2>/dev/null && { echo 'restart failure activated' >&2; exit 1; }
[[ "$(sha256sum "$CADDY_CONFIG_DIR/Caddyfile" | awk '{print $1}')" == "$old_hash" ]]
assert_not_exists "$marker"
unset SYSTEMCTL_RESTART_FAIL

printf ':80 {\n  respond "user"\n}\n' >"$CADDY_CONFIG_DIR/Caddyfile"
unrelated_hash="$(sha256sum "$CADDY_CONFIG_DIR/Caddyfile" | awk '{print $1}')"
activate_managed_caddyfile "$rendered" "$marker" 2>/dev/null && { echo 'unrelated Caddyfile overwritten' >&2; exit 1; }
[[ "$(sha256sum "$CADDY_CONFIG_DIR/Caddyfile" | awk '{print $1}')" == "$unrelated_hash" ]]
printf 'Caddy activation regression tests passed\n'
