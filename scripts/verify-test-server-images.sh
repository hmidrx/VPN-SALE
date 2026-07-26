#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"; secret_tmp="$(mktemp -d)"; project="vpn-sale-acceptance-$$"; env_file="$secret_tmp/runtime.env"
cleanup(){
  local status=$?
  trap - EXIT INT TERM
  docker compose --env-file "$env_file" -p "$project" -f "$tmp/docker-compose.yml" down -v --remove-orphans >/dev/null 2>&1 || true
  for image in api worker telegram customer-web admin-web reseller-web; do docker image rm "$project-$image" >/dev/null 2>&1 || true; done
  chmod -R u+rwX "$tmp" 2>/dev/null || true; rm -rf "$tmp"; rm -rf "$secret_tmp"
  exit "$status"
}

trap cleanup EXIT INT TERM

tar -C "$repo_root" --exclude=.git --exclude=node_modules --exclude=.next -cf - . | tar -C "$tmp" -xf -
find "$tmp" -type d -exec chmod 0700 {} +; find "$tmp" -type f -exec chmod 0600 {} +
while IFS= read -r -d '' entry; do
  mode="${entry%% *}"; path="${entry#*$'\t'}"
  [[ "$mode" == 100755 ]] && chmod 0700 "$tmp/$path"
done < <(git -C "$repo_root" ls-files --stage -z)
cd "$tmp"

# Ephemeral credentials exist only in this mode-0600 file and are never echoed.
umask 077
python3 - "$env_file" <<'PY'
import secrets, sys
from urllib.parse import quote
path=sys.argv[1]
db_password=secrets.token_urlsafe(36)
encoded=quote(db_password, safe="")
async_url="".join(("postgresql", "+asyncpg", "://", "vpnsale", ":", encoded, "@", "postgres", ":5432/vpnsale"))
sync_url="".join(("postgresql", "://", "vpnsale", ":", encoded, "@", "postgres", ":5432/vpnsale"))
values={
 "POSTGRES_USER":"vpnsale", "POSTGRES_DB":"vpnsale", "POSTGRES_PASSWORD":db_password,
 "VPN_SALE_ENVIRONMENT":"test", "VPN_SALE_VERSION":"restrictive-checkout-ci",
 "VPN_SALE_DATABASE_URL":async_url, "DATABASE_URL":async_url,
 "VPN_SALE_SYNC_DATABASE_URL":sync_url,
 "VPN_SALE_REDIS_URL":"redis://redis:6379/0",
 "VPN_SALE_IDENTITY_ENCRYPTION_KEY":secrets.token_urlsafe(48),
 "VPN_SALE_IDENTITY_ENCRYPTION_KEY_VERSION":"ci-v1",
 "VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY":secrets.token_urlsafe(48),
 "VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY":secrets.token_urlsafe(48),
 "VPN_SALE_ADMIN_CSRF_SECRET":secrets.token_urlsafe(48),
 "VPN_SALE_CUSTOMER_CSRF_SECRET":secrets.token_urlsafe(48),
 "VPN_SALE_PROVIDER_WRITES_ENABLED":"false",
 "VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED":"false",
 "VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED":"false",
}
with open(path,"x",encoding="utf-8") as stream:
 for key,value in values.items(): stream.write(f"{key}={value}\n")
PY
chmod 0600 "$env_file"
export ACCEPTANCE_ENV_FILE="$env_file"

docker build -f infra/docker/api.Dockerfile -t "$project-api" .
docker build -f infra/docker/worker.Dockerfile -t "$project-worker" .
docker build -f infra/docker/telegram-bot.Dockerfile -t "$project-telegram" .
for app in customer-web admin-web reseller-web; do
  docker build -f infra/docker/web.Dockerfile --build-arg APP_NAME="$app" --build-arg NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 --build-arg NEXT_PUBLIC_CUSTOMER_API_BASE_URL=http://127.0.0.1:8000 --build-arg NEXT_PUBLIC_TELEGRAM_BOT_USERNAME=disabled_bot --build-arg NEXT_PUBLIC_CUSTOMER_APP_NAME=Test -t "$project-$app" .
done

docker run --rm --entrypoint sh "$project-api" -ec '
  test "$(id -u)" -ne 0
  id
  printf "%s\n" "$PYTHONPATH"
  python -c "import sys; print(sys.path); from platform_api.main import app; assert app"
  test -r /app/apps/api/src/platform_api/main.py
  test -r /app/apps/api/alembic.ini
  test -x /app/apps/api/alembic/versions
  find /app/apps/api/alembic/versions -type f -readable | grep -q .
  alembic --version
'
for image in worker telegram customer-web admin-web reseller-web; do docker run --rm --entrypoint sh "$project-$image" -ec 'test "$(id -u)" -ne 0'; done

cat >docker-compose.yml <<'YAML'
services:
  postgres:
    image: postgres:16
    env_file: ${ACCEPTANCE_ENV_FILE:?runtime env file required}
    healthcheck: {test: [CMD-SHELL, "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"], interval: 2s, timeout: 2s, retries: 30}
  redis:
    image: redis:7
    healthcheck: {test: [CMD, redis-cli, ping], interval: 2s, timeout: 2s, retries: 30}
  api:
    image: ${API_IMAGE:?API image required}
    env_file: ${ACCEPTANCE_ENV_FILE:?runtime env file required}
    ports: ["127.0.0.1:8000:8000"]
    depends_on: {postgres: {condition: service_healthy}, redis: {condition: service_healthy}}
  customer:
    image: ${CUSTOMER_IMAGE:?customer image required}
    ports: ["127.0.0.1:3000:3000"]
  admin:
    image: ${ADMIN_IMAGE:?admin image required}
    ports: ["127.0.0.1:3001:3000"]
  reseller:
    image: ${RESELLER_IMAGE:?reseller image required}
    ports: ["127.0.0.1:3002:3000"]
YAML
export API_IMAGE="$project-api" CUSTOMER_IMAGE="$project-customer-web" ADMIN_IMAGE="$project-admin-web" RESELLER_IMAGE="$project-reseller-web"
compose=(docker compose --env-file "$env_file" -p "$project" -f docker-compose.yml)
# shellcheck source=scripts/test-server-compose-json.sh disable=SC1091
source scripts/test-server-compose-json.sh
"${compose[@]}" up -d postgres redis
wait_compose_service_healthy postgres 120 "${compose[@]}" || {
  "${compose[@]}" ps
  "${compose[@]}" logs --no-color postgres
  exit 1
}
wait_compose_service_healthy redis 120 "${compose[@]}" || {
  "${compose[@]}" ps
  "${compose[@]}" logs --no-color redis
  exit 1
}
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini upgrade head
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini upgrade head
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini current | grep -q '(head)'
"${compose[@]}" up -d api customer admin reseller
for url in http://127.0.0.1:8000/health http://127.0.0.1:8000/ready http://127.0.0.1:8000/version http://127.0.0.1:8000/metrics http://127.0.0.1:3000 http://127.0.0.1:3001 http://127.0.0.1:3002; do "$tmp/scripts/wait-for-http.sh" "$url" 120; done
[[ "$(compose_service_field api RestartCount "${compose[@]}")" == 0 ]]
"${compose[@]}" config --format json | python3 -c 'import json,sys
c=json.load(sys.stdin); expected={"api":[("127.0.0.1",8000)],"customer":[("127.0.0.1",3000)],"admin":[("127.0.0.1",3001)],"reseller":[("127.0.0.1",3002)],"postgres":[],"redis":[]}
actual={name:[(p.get("host_ip"),int(p["published"])) for p in svc.get("ports",[])] for name,svc in c["services"].items()}
assert actual == expected, (actual,expected)'
printf 'restrictive image and real-stack acceptance passed\n'
