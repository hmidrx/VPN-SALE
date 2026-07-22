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
reset_root(){ CADDY_APT_ROOT="$tmp/root-$1"; export CADDY_APT_ROOT TMP_ROOT="$tmp/root-$1" CALLS="$calls"; mkdir -p "$CADDY_APT_ROOT/etc/apt/sources.list.d" "$CADDY_APT_ROOT/usr/share/keyrings"; : >"$calls"; unset CURL_FAIL GPG_FAIL APT_NOPUBKEY_ONCE APT_FAIL_ALWAYS KEY_CONTENT; }

write_stubs
for case_name in missing zero stale valid source-missing-key; do
  reset_root "$case_name"
  [[ "$case_name" == zero ]] && : >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == stale ]] && printf stale >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == valid ]] && printf valid >"$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  [[ "$case_name" == source-missing-key ]] && printf 'deb https://example.invalid stable main\n' >"$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"
  printf unrelated >"$CADDY_APT_ROOT/etc/apt/sources.list.d/unrelated.list"
  install_caddy_apt_repository
  assert_file "$CADDY_APT_ROOT/usr/share/keyrings/caddy-stable-archive-keyring.gpg"
  assert_file "$CADDY_APT_ROOT/etc/apt/sources.list.d/caddy-stable.list"
  grep -Fq unrelated "$CADDY_APT_ROOT/etc/apt/sources.list.d/unrelated.list" || { echo 'unrelated APT file changed' >&2; exit 1; }
done

reset_root curl-fail; CURL_FAIL=true; export CURL_FAIL; if install_caddy_apt_repository; then echo 'failed curl passed' >&2; exit 1; fi
reset_root gpg-fail; GPG_FAIL=true; export GPG_FAIL; if install_caddy_apt_repository; then echo 'failed gpg passed' >&2; exit 1; fi
reset_root no-pubkey; APT_NOPUBKEY_ONCE=true; export APT_NOPUBKEY_ONCE; apt_get_update_with_caddy_retry; [[ "$(cat "$TMP_ROOT/apt-count")" == 2 ]] || { echo 'NO_PUBKEY retry was not bounded to one retry' >&2; exit 1; }

# Static regression for stopping package-default Caddy after installation.
grep -Eq 'apt-get install -y .* caddy' "$repo_root/scripts/install-test-server.sh"
grep -n 'apt-get install -y .* caddy' "$repo_root/scripts/install-test-server.sh" | cut -d: -f1 >"$tmp/install-line"
awk 'seen && /stop_safe_caddy/ {print NR; exit} /apt-get install -y .* caddy/ {seen=1}' "$repo_root/scripts/install-test-server.sh" >"$tmp/stop-line"
[[ "$(cat "$tmp/stop-line")" -gt "$(cat "$tmp/install-line")" ]] || { echo 'caddy not stopped after package install' >&2; exit 1; }

printf 'Caddy APT repository regression tests passed\n'
