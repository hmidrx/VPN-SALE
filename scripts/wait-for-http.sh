#!/usr/bin/env bash
set -Eeuo pipefail
url="${1:?usage: wait-for-http.sh URL [timeout_seconds]}"
timeout="${2:-60}"
deadline=$((SECONDS + timeout))
until curl --fail --silent --show-error "$url" >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Timed out waiting for $url" >&2
    exit 1
  fi
  sleep 2
done
