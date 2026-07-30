#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2317 # Literal-source assertions and EXIT-trap callback.
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verify="$repo_root/scripts/verify-docker.sh"
status_before="$(git -C "$repo_root" status --porcelain)"

if git -C "$repo_root" ls-files --error-unmatch secrets/telegram-internal-token >/dev/null 2>&1; then exit 1; fi
[[ ! -e "$repo_root/secrets/telegram-internal-token" ]]
grep -Fq 'secret_dir="$(mktemp -d)"' "$verify"
grep -Fq 'chmod 0700 "$secret_dir"' "$verify"
grep -Fq 'chmod 0600 "$secret_file"' "$verify"
grep -Fq 'chmod 0640 /fixture/telegram-internal-token' "$verify"
grep -Fq '[[ "$api_gid" == "$bot_gid" ]]' "$verify"
grep -Fq '[[ "$(stat -c %u:%g:%a "$secret_file")" == "0:$api_gid:640" ]]' "$verify"
grep -Fq 'TELEGRAM_INTERNAL_SECRET_READABLE_BY_API' "$verify"
grep -Fq 'TELEGRAM_INTERNAL_SECRET_READABLE_BY_BOT' "$verify"
grep -Fq 'export VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST="$secret_file"' "$verify"
grep -Fq 'rm -rf -- "$secret_dir"' "$verify"
grep -Fq 'http://localhost:8080/api/v1/internal/telegram/profile' "$verify"
if grep -Eq '(cat|printf|echo).*(secret_file|TELEGRAM_INTERNAL_TOKEN)' "$verify"; then exit 1; fi

exercise_cleanup() {
  local outcome="$1" marker secret_dir=""
  marker="$(mktemp)"
  rm -f "$marker"
  (
    cleanup_fixture() {
      local status=$?
      [[ -z "$secret_dir" || ! -d "$secret_dir" ]] || rm -rf -- "$secret_dir"
      exit "$status"
    }
    trap cleanup_fixture EXIT
    secret_dir="$(mktemp -d)"
    chmod 0700 "$secret_dir"
    printf '%s' "$secret_dir" >"$marker"
    token_file="$secret_dir/telegram-internal-token"
    python - "$token_file" <<'PY'
from pathlib import Path
import secrets
import sys
Path(sys.argv[1]).write_text(secrets.token_urlsafe(48), encoding="utf-8")
PY
    chmod 0600 "$token_file"
    [[ "$(stat -c %a "$token_file")" == 600 ]]
    [[ "$outcome" == success ]] || false
  ) >/dev/null 2>&1 || [[ "$outcome" == failure ]]
  removed_dir="$(cat "$marker")"
  rm -f "$marker"
  [[ ! -e "$removed_dir" ]]
}

exercise_cleanup success
exercise_cleanup failure
[[ ! -e "$repo_root/secrets/telegram-internal-token" ]]
[[ "$(git -C "$repo_root" status --porcelain)" == "$status_before" ]]
printf 'verify-docker temporary secret lifecycle passed\n'
