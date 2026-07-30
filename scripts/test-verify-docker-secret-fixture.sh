#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
verify="$repo_root/scripts/verify-docker.sh"

! git -C "$repo_root" ls-files --error-unmatch secrets/telegram-internal-token >/dev/null 2>&1
[[ ! -e "$repo_root/secrets/telegram-internal-token" ]]
grep -Fq 'secret_dir="$(mktemp -d)"' "$verify"
grep -Fq 'chmod 0700 "$secret_dir"' "$verify"
grep -Fq 'chmod 0600 "$secret_file"' "$verify"
grep -Fq 'export VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST="$secret_file"' "$verify"
grep -Fq 'rm -rf -- "$secret_dir"' "$verify"
grep -Fq 'http://localhost:8080/api/v1/internal/telegram/profile' "$verify"
! grep -Eq '(cat|printf|echo).*(secret_file|TELEGRAM_INTERNAL_TOKEN)' "$verify"

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
git -C "$repo_root" diff --quiet -- . ':!scripts/verify-docker.sh' ':!scripts/test-verify-docker-secret-fixture.sh'
printf 'verify-docker temporary secret lifecycle passed\n'
