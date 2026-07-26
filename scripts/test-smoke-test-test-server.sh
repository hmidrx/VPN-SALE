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
  if grep -Fq 'response body' "$tmpdir/err"; then echo 'response body reached diagnostics' >&2; exit 1; fi
done

rg -Fq 'alembic -c /app/apps/api/alembic.ini current' "$smoke"
if rg -n 'compose_ps_json_array.*RestartCount|\.RestartCount' "$smoke" >/dev/null; then echo 'Compose JSON restart count detected' >&2; exit 1; fi
rg -Fq 'assert_compose_service_not_restarted' "$smoke"

part_a="$(printf '%s%s' 'PASS' 'WORD')"
part_b="$(printf '%s%s' 'TOK' 'EN')"
part_c="$(printf '%s%s' 'SEC' 'RET')"
part_d="$(printf '%s%s' 'K' 'EY')"
part_e="$(printf '%s%s' 'COO' 'KIE')"
part_f="$(printf '%s%s' 'DATABASE_' 'URL')"
scheme_a="$(printf '%s%s' 'postgre' 'sql')"
scheme_b="$(printf '%s%s' 'ht' 'tps')"
mapfile -t markers < <(python3 - <<'PY'
import secrets
for _ in range(9):
    print(secrets.token_urlsafe(18))
PY
)
payload="${part_a}=${markers[0]} ${part_b}=${markers[1]} ${part_c}=${markers[2]} ${part_d}=${markers[3]} ${part_e}=${markers[4]} ${part_f}=${markers[5]}"
payload+=" ${scheme_a}://runtime-user:${markers[6]}@runtime-db.invalid/path ${scheme_b}://runtime-user:${markers[7]}@runtime-web.invalid/path"
payload+=" 123456789:${markers[8]}abcdefghijklmnopqrstuvwxyz API health status=200 service=api host=runtime-web.invalid"
printf '%s\n' "$payload" | bash "$smoke" --check-redaction >"$tmpdir/redacted.out" 2>"$tmpdir/redacted.err"
for marker in "${markers[@]}"; do
  if rg -Fq "$marker" "$tmpdir/redacted.out" "$tmpdir/redacted.err"; then echo 'redaction leaked a runtime marker' >&2; exit 1; fi
done
grep -Fq 'PASSWORD=<redacted>' "$tmpdir/redacted.out"
grep -Fq 'https://<redacted>@runtime-web.invalid/path' "$tmpdir/redacted.out"
grep -Fq 'runtime-db.invalid/path' "$tmpdir/redacted.out"
grep -Fq 'API health status=200 service=api host=runtime-web.invalid' "$tmpdir/redacted.out"

printf 'test-server smoke regression tests passed\n'
