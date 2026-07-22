#!/usr/bin/env bash
set -Eeuo pipefail
url="${1:?usage: wait-for-http.sh URL [timeout_seconds]}"
timeout="${2:-60}"
deadline=$((SECONDS + timeout))
last_error_file="$(mktemp)"
trap 'rm -f "$last_error_file"' EXIT
until curl --fail --silent --show-error --connect-timeout 5 --max-time 10 "$url" >/dev/null 2>"$last_error_file"; do
  if (( SECONDS >= deadline )); then
    printf 'Timed out waiting for %s' "$url" >&2
    if [[ -s "$last_error_file" ]]; then
      printf ': ' >&2
      tr '\n' ' ' <"$last_error_file" >&2
    fi
    printf '\n' >&2
    exit 1
  fi
  sleep 2
done
