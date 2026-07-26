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

sanitize_service_diagnostics(){
  sed -E \
    -e 's/((DATABASE_URL|PASSWORD|TOKEN|COOKIE|SECRET|KEY)=)[^[:space:]]+/\1<redacted>/Ig' \
    -e 's#(postgresql(\+asyncpg)?|redis|https?)://[^[:space:]]+#\1://<redacted>#Ig'
}

compose_service_container_id(){
  local service="$1"; shift
  local -a compose_cmd=("$@") ids=()
  mapfile -t ids < <("${compose_cmd[@]}" ps -q "$service" | sed '/^[[:space:]]*$/d')
  if (( ${#ids[@]} != 1 )); then
    printf 'Service %s must have exactly one container; found %s.\n' "$service" "${#ids[@]}" >&2
    return 1
  fi
  printf '%s\n' "${ids[0]}"
}

docker_container_restart_count(){
  local container_id="$1" docker_bin="${VPN_SALE_DOCKER_BIN:-docker}" restart_count
  if ! restart_count="$("$docker_bin" inspect --format '{{.RestartCount}}' "$container_id" 2>/dev/null)"; then
    printf 'Docker inspect failed for container %s.\n' "$container_id" >&2
    return 1
  fi
  if [[ ! "$restart_count" =~ ^[0-9]+$ ]]; then
    printf 'Container %s has missing or invalid restart count.\n' "$container_id" >&2
    return 1
  fi
  printf '%s\n' "$restart_count"
}

compose_service_safe_diagnostics(){
  local service="$1" container_id="${2:-unavailable}"; shift 2
  local -a compose_cmd=("$@")
  local docker_bin="${VPN_SALE_DOCKER_BIN:-docker}" state="unavailable" health="unavailable" restarts="unavailable"
  if [[ "$container_id" != unavailable ]]; then
    state="$("$docker_bin" inspect --format '{{.State.Status}}' "$container_id" 2>/dev/null || printf unavailable)"
    health="$("$docker_bin" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unavailable{{end}}' "$container_id" 2>/dev/null || printf unavailable)"
    restarts="$("$docker_bin" inspect --format '{{.RestartCount}}' "$container_id" 2>/dev/null || printf unavailable)"
  fi
  printf 'Service %s diagnostics: state=%s health=%s restart_count=%s\n' "$service" "$state" "$health" "$restarts" >&2
  "${compose_cmd[@]}" ps 2>&1 | sanitize_service_diagnostics >&2 || true
  "${compose_cmd[@]}" logs --no-color "$service" 2>&1 | sanitize_service_diagnostics >&2 || true
}

assert_compose_service_not_restarted(){
  local service="$1"; shift
  local -a compose_cmd=("$@")
  local container_id="" restart_count=""
  if ! container_id="$(compose_service_container_id "$service" "${compose_cmd[@]}")"; then
    compose_service_safe_diagnostics "$service" unavailable "${compose_cmd[@]}"
    return 1
  fi
  if ! restart_count="$(docker_container_restart_count "$container_id")"; then
    compose_service_safe_diagnostics "$service" "$container_id" "${compose_cmd[@]}"
    return 1
  fi
  if [[ "$restart_count" != 0 ]]; then
    printf 'Service %s restarted %s time(s); expected zero.\n' "$service" "$restart_count" >&2
    compose_service_safe_diagnostics "$service" "$container_id" "${compose_cmd[@]}"
    return 1
  fi
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
