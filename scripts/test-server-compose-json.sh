#!/usr/bin/env bash
# Helpers for Docker Compose ps JSON compatibility in test-server scripts.

normalize_compose_ps_json(){
  jq -s 'if length == 1 and (.[0] | type) == "array" then .[0] else . end'
}

compose_ps_json_array(){
  local -a compose_cmd=("$@")
  "${compose_cmd[@]}" ps --format json | normalize_compose_ps_json
}

compose_service_json_array(){
  local service="$1"; shift
  local -a compose_cmd=("$@")
  "${compose_cmd[@]}" ps --format json "$service" | normalize_compose_ps_json
}

compose_service_field(){
  local service="$1" field="$2"; shift 2
  compose_service_json_array "$service" "$@" | jq -er --arg service "$service" --arg field "$field" '
    map(select(.Service == $service)) | first | if . == null then empty else .[$field] // empty end
  '
}

wait_compose_service_healthy(){
  local service="$1" timeout_seconds="$2"; shift 2
  local -a compose_cmd=("$@")
  local deadline=$((SECONDS + timeout_seconds))
  local health=""
  while (( SECONDS < deadline )); do
    if health="$(compose_service_field "$service" Health "${compose_cmd[@]}" 2>/dev/null)"; then
      case "$health" in
        healthy) return 0 ;;
        unhealthy)
          printf 'Service %s reported unhealthy while waiting for readiness (diagnostics redacted; inspect service logs).\n' "$service" >&2
          return 1
          ;;
      esac
    fi
    sleep 2
  done
  health="$(compose_service_field "$service" Health "${compose_cmd[@]}" 2>/dev/null || true)"
  printf 'Service %s did not become healthy within %ss (last health: %s)\n' "$service" "$timeout_seconds" "${health:-unavailable}" >&2
  return 1
}
