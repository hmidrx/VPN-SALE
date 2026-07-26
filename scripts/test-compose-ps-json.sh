#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-compose-json.sh
source "$repo_root/scripts/test-server-compose-json.sh"

tmpdir="$(mktemp -d)"
cleanup(){ local status=$?; trap - EXIT; rm -rf "$tmpdir"; exit "$status"; }
trap cleanup EXIT

make_compose(){
  local payload="$1" delay_file="${2:-}"
  cat >"$tmpdir/compose" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "ps" ]]; then
  shift
  service=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --format) shift 2 ;;
      *) service="$1"; shift ;;
    esac
  done
  if [[ -n "${DELAY_FILE:-}" ]]; then
    count=0
    [[ -f "$DELAY_FILE" ]] && count="$(cat "$DELAY_FILE")"
    count=$((count + 1)); printf '%s' "$count" >"$DELAY_FILE"
    if (( count < 2 )); then printf '%s\n' '{"Service":"postgres","Health":"starting"}'; exit 0; fi
  fi
  if [[ -n "$service" ]]; then
    printf '%s' "$PAYLOAD" | jq -s -c --arg service "$service" 'if length == 1 and (.[0] | type) == "array" then .[0][] else .[] end | select(.Service == $service)' 2>/dev/null || printf '%s' "$PAYLOAD"
  else
    printf '%s' "$PAYLOAD"
  fi
  exit 0
fi
exit 2
SH
  chmod +x "$tmpdir/compose"
  export PAYLOAD="$payload" DELAY_FILE="$delay_file"
}

assert_count(){ local expected="$1" payload="$2"; make_compose "$payload"; [[ "$(compose_ps_json_array "$tmpdir/compose" | jq 'length')" == "$expected" ]]; }
assert_count 2 '[{"Service":"postgres","Health":"healthy"},{"Service":"redis","Health":"healthy"}]'
assert_count 2 $'{"Service":"postgres","Health":"healthy"}\n{"Service":"redis","Health":"healthy"}\n'
assert_count 1 '{"Service":"postgres","Health":"healthy"}'
assert_count 0 ''
make_compose $'{"Service":"redis","Health":"healthy"}\n{"Service":"postgres","Health":"healthy"}\n'
[[ "$(compose_service_field postgres Health "$tmpdir/compose")" == healthy ]]
[[ "$(compose_service_field redis Health "$tmpdir/compose")" == healthy ]]
make_compose '{"Service":"postgres","Health":"unhealthy"}'
if wait_compose_service_healthy postgres 1 "$tmpdir/compose" 2>"$tmpdir/timeout.err"; then echo 'unhealthy service passed' >&2; exit 1; fi
grep -Fq 'reported unhealthy' "$tmpdir/timeout.err"
grep -Fq 'diagnostics redacted' "$tmpdir/timeout.err"
make_compose '{"Service":"postgres","Health":"starting"}'
if wait_compose_service_healthy postgres 1 "$tmpdir/compose" 2>"$tmpdir/starting.err"; then echo 'permanently starting service passed' >&2; exit 1; fi
grep -Fq 'did not become healthy within 1s' "$tmpdir/starting.err"
grep -Fq 'last health: starting' "$tmpdir/starting.err"
make_compose '{"Service":"redis","Health":"healthy"}'
if wait_compose_service_healthy postgres 1 "$tmpdir/compose" 2>"$tmpdir/missing.err"; then echo 'missing service passed' >&2; exit 1; fi
grep -Fq 'last health: unavailable' "$tmpdir/missing.err"
make_compose '{not json}'
if compose_ps_json_array "$tmpdir/compose" >/dev/null 2>"$tmpdir/malformed.err"; then echo 'malformed JSON passed' >&2; exit 1; fi
make_compose '{"Service":"postgres","Health":"healthy"}' "$tmpdir/delay.count"
wait_compose_service_healthy postgres 5 "$tmpdir/compose"

cat >"$tmpdir/restart-compose" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  ps)
    if [[ "${2:-}" == -q ]]; then printf '%b' "${COMPOSE_IDS:-}"; else printf 'safe compose status\n'; fi
    ;;
  logs) printf 'safe log PASSWORD=%s DATABASE_URL=%s\n' "${FAKE_SECRET_VALUE:?}" "${FAKE_SECRET_VALUE:?}" ;;
  *) exit 2 ;;
esac
SH
cat >"$tmpdir/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == inspect && "${2:-}" == --format ]] || exit 2
[[ "${INSPECT_FAIL:-false}" != true ]] || exit 19
case "$3" in
  '{{.RestartCount}}') if [[ "${MISSING_RESTART:-false}" != true ]]; then printf '%s\n' "${DOCKER_RESTART:-0}"; fi ;;
  '{{.State.Status}}') printf 'running\n' ;;
  '{{if .State.Health}}{{.State.Health.Status}}{{else}}unavailable{{end}}') printf 'healthy\n' ;;
  *) exit 2 ;;
esac
SH
chmod +x "$tmpdir/restart-compose" "$tmpdir/docker"
export VPN_SALE_DOCKER_BIN="$tmpdir/docker"
FAKE_SECRET_VALUE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"; export FAKE_SECRET_VALUE
assert_restart_failure(){
  local expected="$1" output
  if output="$(assert_compose_service_not_restarted api "$tmpdir/restart-compose" 2>&1)"; then echo "restart case unexpectedly passed: $expected" >&2; exit 1; fi
  grep -Fq "$expected" <<<"$output"
  if grep -Fq "$FAKE_SECRET_VALUE" <<<"$output"; then echo 'diagnostics leaked a secret value' >&2; exit 1; fi
  grep -Fq 'runtime environment omitted' <<<"$output"
}
COMPOSE_IDS=$'api-id\n'; DOCKER_RESTART=0; export COMPOSE_IDS DOCKER_RESTART; unset INSPECT_FAIL MISSING_RESTART
assert_compose_service_not_restarted api "$tmpdir/restart-compose"
DOCKER_RESTART=1; assert_restart_failure 'restarted 1 time(s)'
COMPOSE_IDS=''; DOCKER_RESTART=0; assert_restart_failure 'exactly one container; found 0'
COMPOSE_IDS=$'api-one\napi-two\n'; assert_restart_failure 'exactly one container; found 2'
COMPOSE_IDS=$'api-id\n'; export INSPECT_FAIL=true; assert_restart_failure 'Docker inspect failed'
unset INSPECT_FAIL; export MISSING_RESTART=true; assert_restart_failure 'missing or invalid restart count'
unset MISSING_RESTART; DOCKER_RESTART=invalid; assert_restart_failure 'missing or invalid restart count'
set +e
bash -c 'd="$(mktemp -d)"; cleanup(){ s=$?; trap - EXIT; rm -rf "$d"; exit "$s"; }; trap cleanup EXIT; exit 37'
cleanup_status=$?
set -e
[[ "$cleanup_status" == 37 ]]
if rg -n 'down -v|docker volume rm .*redis|redis.*volume rm' "$repo_root/scripts/install-test-server.sh" "$repo_root/scripts/smoke-test-test-server.sh"; then echo 'destructive volume command found' >&2; exit 1; fi
printf 'compose ps JSON parser tests passed\n'
