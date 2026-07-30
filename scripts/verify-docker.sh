#!/usr/bin/env bash
set -Eeuo pipefail

log() { printf '\n==> %s\n' "$*"; }
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 127; }; }
need_cmd docker
need_cmd curl
need_cmd jq
need_cmd python
secret_dir=""
cleanup() {
  status=$?
  if [[ $status -ne 0 ]]; then
    docker compose logs --no-color api reverse-proxy postgres redis || true
  fi
  docker compose down --volumes --remove-orphans || true
  if [[ -n "$secret_dir" && -d "$secret_dir" ]]; then
    rm -rf -- "$secret_dir"
  fi
  exit "$status"
}
trap cleanup EXIT

secret_dir="$(mktemp -d)"
chmod 0700 "$secret_dir"
secret_file="$secret_dir/telegram-internal-token"
python - "$secret_file" <<'PY'
from pathlib import Path
import secrets
import sys

Path(sys.argv[1]).write_text(secrets.token_urlsafe(48), encoding="utf-8")
PY
chmod 0600 "$secret_file"
export VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST="$secret_file"

log "Docker versions"
docker --version
docker compose version
log "Compose config"
docker compose config

log "Test-server Compose port isolation"
"$repo_root/scripts/verify-test-server-compose.sh"
log "Build core images"
docker compose --profile telegram build api telegram-bot
api_image="$(docker compose images -q api)"
bot_image="$(docker compose --profile telegram images -q telegram-bot)"
[[ -n "$api_image" && -n "$bot_image" ]]
api_identity="$(docker run --rm --network none --entrypoint sh "$api_image" -c \
  'printf "%s:%s" "$(id -u vpnsale)" "$(id -g vpnsale)"')"
bot_identity="$(docker run --rm --network none --entrypoint sh "$bot_image" -c \
  'printf "%s:%s" "$(id -u vpnsale)" "$(id -g vpnsale)"')"
IFS=: read -r api_uid api_gid <<<"$api_identity"
IFS=: read -r bot_uid bot_gid <<<"$bot_identity"
[[ "$api_uid" =~ ^[0-9]+$ && "$api_gid" =~ ^[0-9]+$ && "$api_uid" -ne 0 ]]
[[ "$bot_uid" =~ ^[0-9]+$ && "$bot_gid" =~ ^[0-9]+$ && "$bot_uid" -ne 0 ]]
[[ "$api_gid" == "$bot_gid" ]]
printf 'API runtime identity: uid=%s gid=%s\n' "$api_uid" "$api_gid"
printf 'Telegram bot runtime identity: uid=%s gid=%s\n' "$bot_uid" "$bot_gid"
docker run --rm --network none --user 0:0 \
  --mount "type=bind,src=$secret_dir,dst=/fixture" --entrypoint sh "$api_image" \
  -c 'chown 0:"$1" /fixture/telegram-internal-token && chmod 0640 /fixture/telegram-internal-token' \
  helper "$api_gid"
[[ "$(stat -c %u:%g:%a "$secret_file")" == "0:$api_gid:640" ]]
log "Start core stack"
docker compose up -d postgres redis api reverse-proxy
log "Verify private Telegram credential mount"
docker compose exec -T api python - <<'PY'
from pathlib import Path

value = Path("/run/secrets/telegram-internal-token").read_text(encoding="utf-8").strip()
assert __import__("os").getuid() != 0
assert len(value) >= 43
print("TELEGRAM_INTERNAL_SECRET_READABLE_BY_API")
PY
log "Verify Telegram bot runtime credential mount"
docker run --rm --network none --user "$bot_uid:$bot_gid" \
  --mount "type=bind,src=$secret_file,dst=/run/secrets/telegram-internal-token,readonly" \
  --entrypoint python "$bot_image" - <<'PY'
from pathlib import Path
import os

assert os.getuid() != 0
value = Path("/run/secrets/telegram-internal-token").read_text(encoding="utf-8").strip()
assert len(value) >= 43
print("TELEGRAM_INTERNAL_SECRET_READABLE_BY_BOT")
PY
log "Wait for proxy endpoints"
scripts/wait-for-http.sh http://localhost:8080/health 90
scripts/wait-for-http.sh http://localhost:8080/version 90
scripts/wait-for-http.sh http://localhost:8080/metrics 90
scripts/wait-for-http.sh http://localhost:8080/ready 90
log "Compose status"
docker compose ps
log "Synchronous PostgreSQL runtime check"
sync_check="$(docker compose exec -T api python -m platform_api.sync_database_check)"
[[ "$sync_check" == "PASS" ]]
printf '%s\n' "$sync_check"
log "Verify endpoint responses"
health="$(curl --fail --silent http://localhost:8080/health)"
ready="$(curl --fail --silent http://localhost:8080/ready)"
version="$(curl --fail --silent http://localhost:8080/version)"
metrics="$(curl --fail --silent http://localhost:8080/metrics)"
internal_code="$(curl --silent --output /dev/null --write-out '%{http_code}' \
  http://localhost:8080/api/v1/internal/telegram/profile)"
[[ "$internal_code" == 404 ]]
printf '%s' "$health" | jq -e '.status == "ok"' >/dev/null
printf '%s' "$ready" | jq -e '.status == "ready" and .checks.database == true and .checks.redis == true' >/dev/null
printf '%s' "$version" | jq -e '.version and .environment' >/dev/null
printf '%s' "$metrics" | grep -q 'vpnsale_api_info'
for endpoint in register password-login; do
  code="$(curl --silent --output /dev/null --dump-header /tmp/vpnsale-disabled-auth-headers \
    --write-out '%{http_code}' \
    -X POST -H 'content-type: application/json' --data '{}' \
    "http://localhost:8080/api/v1/customer/auth/$endpoint")"
  [[ "$code" == 404 ]]
  if grep -qi '^set-cookie:' /tmp/vpnsale-disabled-auth-headers; then exit 1; fi
done
rm -f /tmp/vpnsale-disabled-auth-headers
combined="$health$ready$version$metrics"
if printf '%s' "$combined" | grep -Eiq '(password|secret|token|cookie|vless://|vmess://|trojan://)'; then
  echo "Endpoint response contained a forbidden sensitive marker." >&2
  exit 1
fi
log "Docker stack verification passed"
