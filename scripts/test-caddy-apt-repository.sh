#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-installer-lib.sh
source "$repo_root/scripts/test-server-installer-lib.sh"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
calls="$tmp/calls"
mkdir -p "$tmp/bin"
export PATH="$tmp/bin:$PATH"

write_stubs(){
  cat >"$tmp/bin/curl" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$CALLS"
out=""
url=""
while (($#)); do case "$1" in -o) out="$2"; shift 2;; http*) url="$1"; shift;; *) shift;; esac; done
[[ "${CURL_FAIL:-false}" != true ]] || exit 22
[[ -n "$out" ]] || exit 2
case "$url" in
  *gpg.key) printf '%s\n' "${KEY_CONTENT:-fake-key}" >"$out" ;;
  *debian.deb.txt) printf '%s\n' "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" >"$out" ;;
  *) exit 3 ;;
esac
STUB
  cat >"$tmp/bin/gpg" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf 'gpg %s\n' "$*" >>"$CALLS"
out=""
in="${@: -1}"
if [[ "${1:-}" == "--batch" && "${2:-}" == "--show-keys" ]]; then
  [[ -s "${3:?}" ]] || exit 2
  ! grep -Fq invalid "${3:?}" || exit 2
  exit 0
fi
while (($#)); do case "$1" in --output) out="$2"; shift 2;; *) shift;; esac; done
[[ "${GPG_FAIL:-false}" != true ]] || exit 2
[[ -n "$out" ]] || exit 3
cat "$in" >"$out"
STUB
  cat >"$tmp/bin/apt-get" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf 'apt-get %s\n' "$*" >>"$CALLS"
count_file="$TMP_ROOT/apt-count"
count=0; [[ -f "$count_file" ]] && count="$(cat "$count_file")"
count=$((count+1)); printf '%s' "$count" >"$count_file"
source_file="$TMP_ROOT/etc/apt/sources.list.d/caddy-stable.list"
if [[ "${APT_FAIL_IF_BROKEN_CADDY_ACTIVE:-false}" == true && -f "$source_file" && ! -s "$TMP_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg" ]]; then
  echo "apt-get update saw active broken Caddy source before quarantine" >&2
  exit 88
fi
if [[ "${APT_NOPUBKEY_ONCE:-false}" == true && "$count" -eq 1 ]]; then
  echo 'Err: https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version InRelease' >&2
  echo 'NO_PUBKEY ABA1F9B8875A6661' >&2
  exit 100
fi
if [[ "${APT_FAIL_ALWAYS:-false}" == true ]]; then echo 'apt failed' >&2; exit 100; fi
exit 0
STUB
  chmod +x "$tmp/bin/curl" "$tmp/bin/gpg" "$tmp/bin/apt-get"
}

assert_file(){ [[ -s "$1" ]] || { echo "missing/non-empty check failed: $1" >&2; exit 1; }; [[ "$(stat -c %a "$1")" == 644 ]] || { echo "mode check failed: $1" >&2; exit 1; }; }
assert_no_duplicate_caddy_source(){ [[ $(find "$CADDY_APT_ROOT/etc/apt/sources.list.d" -maxdepth 1 -name "*.list" -type f -exec grep -El "^[[:space:]]*deb[[:space:]].*dl[.]cloudsmith[.]io/public/caddy/stable" {} + | wc -l) -eq 1 ]] || { echo "duplicate active Caddy source" >&2; exit 1; }; }
managed_old_source(){ printf 'deb [signed-by=/etc/apt/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main\n' >"$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"; }
run_package_order_until_caddy_install(){ quarantine_broken_installer_caddy_source; apt-get update; apt-get install -y ca-certificates curl gnupg debian-keyring debian-archive-keyring apt-transport-https; install_caddy_apt_repository; apt_get_update_with_caddy_retry; apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin caddy; }
reset_root(){ CADDY_APT_ROOT="$tmp/root-$1"; export CADDY_APT_ROOT TMP_ROOT="$tmp/root-$1" CALLS="$calls"; mkdir -p "$CADDY_APT_ROOT/etc/apt/sources.list.d" "$CADDY_APT_ROOT/usr/share/keyrings"; : >"$calls"; unset CURL_FAIL GPG_FAIL APT_NOPUBKEY_ONCE APT_FAIL_ALWAYS KEY_CONTENT; }

write_stubs
for case_name in missing zero stale valid source-missing-key; do
  reset_root "$case_name"
  [[ "$case_name" == zero ]] && : >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == stale ]] && printf stale >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == valid ]] && printf valid >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == source-missing-key ]] && printf 'deb https://example.invalid stable main\n' >"$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"
  [[ "$case_name" == stale ]] && printf invalid >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  printf unrelated >"$CADDY_APT_ROOT/etc/apt/sources.list.d/unrelated.list"
  install_caddy_apt_repository
  assert_file "$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  assert_file "$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"
  assert_no_duplicate_caddy_source
  grep -Fq unrelated "$CADDY_APT_ROOT/etc/apt/sources.list.d/unrelated.list" || { echo 'unrelated APT file changed' >&2; exit 1; }
done

reset_root curl-fail; CURL_FAIL=true; export CURL_FAIL; if install_caddy_apt_repository; then echo 'failed curl passed' >&2; exit 1; fi
reset_root gpg-fail; GPG_FAIL=true; export GPG_FAIL; if install_caddy_apt_repository; then echo 'failed gpg passed' >&2; exit 1; fi
reset_root no-pubkey; APT_NOPUBKEY_ONCE=true; export APT_NOPUBKEY_ONCE; apt_get_update_with_caddy_retry; [[ "$(cat "$TMP_ROOT/apt-count")" == 2 ]] || { echo 'NO_PUBKEY retry was not bounded to one retry' >&2; exit 1; }

for case_name in interrupted-before-key interrupted-after-source missing-key zero-key invalid-key second-rerun; do
  reset_root "$case_name"
  managed_old_source
  printf unrelated >"$CADDY_APT_ROOT/etc/apt/sources.list.d/unrelated.list"
  [[ "$case_name" == zero-key ]] && : >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == invalid-key ]] && printf invalid >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  APT_FAIL_IF_BROKEN_CADDY_ACTIVE=true; export APT_FAIL_IF_BROKEN_CADDY_ACTIVE
  run_package_order_until_caddy_install
  if [[ "$case_name" == second-rerun ]]; then run_package_order_until_caddy_install; fi
  assert_file "$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  assert_file "$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"
  assert_no_duplicate_caddy_source
  grep -Fq unrelated "$CADDY_APT_ROOT/etc/apt/sources.list.d/unrelated.list" || { echo 'unrelated APT file changed during package order' >&2; exit 1; }
  if grep -n 'apt-get update' "$calls" | head -n1 | cut -d: -f1 | grep -q .; then :; else echo 'missing apt-get update in order test' >&2; exit 1; fi
done

reset_root custom-caddy-source
printf 'deb [signed-by=/custom/key.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main\n' >"$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"
if quarantine_broken_installer_caddy_source 2>/dev/null; then echo 'custom Caddy source was not rejected' >&2; exit 1; fi

# Static regression for stopping package-default Caddy after installation.
grep -Eq 'apt-get install -y .* caddy' "$repo_root/scripts/install-test-server.sh"
grep -n 'apt-get install -y .* caddy' "$repo_root/scripts/install-test-server.sh" | cut -d: -f1 >"$tmp/install-line"
awk 'seen && /stop_safe_caddy/ {print NR; exit} /apt-get install -y .* caddy/ {seen=1}' "$repo_root/scripts/install-test-server.sh" >"$tmp/stop-line"
[[ "$(cat "$tmp/stop-line")" -gt "$(cat "$tmp/install-line")" ]] || { echo 'caddy not stopped after package install' >&2; exit 1; }

printf 'Caddy APT repository regression tests passed\n'
