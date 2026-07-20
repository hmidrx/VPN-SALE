#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/test-server-compose-json.sh
source "$repo_root/scripts/test-server-compose-json.sh"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

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
grep -Fq 'did not become healthy within 1s' "$tmpdir/timeout.err"
make_compose '{not json}'
if compose_ps_json_array "$tmpdir/compose" >/dev/null 2>"$tmpdir/malformed.err"; then echo 'malformed JSON passed' >&2; exit 1; fi
make_compose '{"Service":"postgres","Health":"healthy"}' "$tmpdir/delay.count"
wait_compose_service_healthy postgres 5 "$tmpdir/compose"
if rg -n 'down -v|docker volume rm .*redis|redis.*volume rm' "$repo_root/scripts/install-test-server.sh" "$repo_root/scripts/smoke-test-test-server.sh"; then echo 'destructive volume command found' >&2; exit 1; fi
printf 'compose ps JSON parser tests passed\n'
