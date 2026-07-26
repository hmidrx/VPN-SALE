#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smoke="$repo_root/scripts/smoke-test-test-server.sh"
tmpdir="$(mktemp -d)"
cleanup(){ local status=$?; trap - EXIT; rm -rf "$tmpdir"; exit "$status"; }
trap cleanup EXIT

cat >"$tmpdir/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" >"${CURL_ARGS:?}"
if [[ " $* " == *' --head '* || " $* " == *' -I '* || " $* " == *' -fsSI '* ]]; then exit 22; fi
if [[ " $* " != *' --output /dev/null '* ]]; then printf 'response body that must never be printed\n'; fi
[[ "${CURL_HTTP_STATUS:-200}" == 200 ]] || exit 22
SH
chmod +x "$tmpdir/curl"
export PATH="$tmpdir:$PATH" CURL_ARGS="$tmpdir/curl.args"

run_check(){ PATH="$PATH" bash "$smoke" --check-public-url 'API health' 'https://api.example.test/health'; }
output="$(CURL_HTTP_STATUS=200 run_check 2>&1)"
[[ -z "$output" ]]
grep -Fxq -- '--fail' "$CURL_ARGS"
grep -Fxq -- '--silent' "$CURL_ARGS"
grep -Fxq -- '--show-error' "$CURL_ARGS"
grep -Fxq -- '--output' "$CURL_ARGS"
grep -Fxq -- '/dev/null' "$CURL_ARGS"
grep -Fxq -- '--connect-timeout' "$CURL_ARGS"
grep -Fxq -- '--max-time' "$CURL_ARGS"
if rg -x -- '--head|-I|-k|--insecure' "$CURL_ARGS" >/dev/null; then echo 'HEAD or disabled TLS verification detected' >&2; exit 1; fi

for status in 404 500; do
  if CURL_HTTP_STATUS="$status" run_check >"$tmpdir/out" 2>"$tmpdir/err"; then echo "GET $status passed" >&2; exit 1; fi
  [[ ! -s "$tmpdir/out" ]]
  grep -Fq 'ERROR: API health public HTTPS GET failed' "$tmpdir/err"
  ! grep -Fq 'response body' "$tmpdir/err"
done

rg -Fq 'alembic -c /app/apps/api/alembic.ini current' "$smoke"
! rg -n 'compose_ps_json_array.*RestartCount|\.RestartCount' "$smoke" >/dev/null
rg -Fq 'assert_compose_service_not_restarted' "$smoke"

secret='PASSWORD=not-for-diagnostics TOKEN=also-private DATABASE_URL=postgresql://private COOKIE=session KEY=value'
if CURL_HTTP_STATUS=500 "$tmpdir/curl" --fail "$secret" >/dev/null 2>"$tmpdir/secret.err"; then exit 1; fi
diagnostic="$(printf '%s' "$secret" | sed -E 's/(TOKEN|PASSWORD|SECRET|KEY)=([^[:space:]]+)/\1=<redacted>/g')"
[[ "$diagnostic" != *not-for-diagnostics* && "$diagnostic" != *also-private* ]]

printf 'test-server smoke regression tests passed\n'
