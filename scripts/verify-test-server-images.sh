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
 "VPN_SALE_PUBLIC_APP_ORIGIN":"https://app.dr-ping.com",
 "VPN_SALE_CORS_ALLOWED_ORIGINS":"[\"https://app.dr-ping.com\",\"https://admin.dr-ping.com\",\"https://reseller.dr-ping.com\"]",
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
printf 'database services healthy\n'
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini upgrade 0029_unified_account_schema
"${compose[@]}" exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT to_regclass('\''public.telegram_link_challenges'\'') IS NULL"' | grep -qx t
printf 'historical migration isolation confirmed\n'
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini upgrade head
printf 'first migration complete\n'
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini upgrade head
printf 'second migration complete\n'
"${compose[@]}" run --rm api alembic -c /app/apps/api/alembic.ini current | grep -Eq '0030_telegram_link_challenges.*\(head\)'
"${compose[@]}" exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT to_regclass('\''public.telegram_link_challenges'\'') IS NOT NULL"' | grep -qx t
printf 'migration head confirmed\n'
"${compose[@]}" up -d api customer admin reseller
printf 'application containers started\n'
sync_check="$("${compose[@]}" exec -T api python -m platform_api.sync_database_check)"
[[ "$sync_check" == "PASS" ]]
printf '%s\n' "$sync_check"
wait_endpoint(){
  local label="$1" url="$2" service="$3"
  if ! "$tmp/scripts/wait-for-http.sh" "$url" 120; then
    printf 'Endpoint failed: %s\n' "$label" >&2
    compose_service_safe_diagnostics "$service" "$(compose_service_container_id "$service" "${compose[@]}" 2>/dev/null || printf unavailable)" "${compose[@]}"
    return 1
  fi
  printf '%s ready\n' "$label"
}
wait_endpoint 'API health' http://127.0.0.1:8000/health api
wait_endpoint 'API readiness' http://127.0.0.1:8000/ready api
wait_endpoint 'API version' http://127.0.0.1:8000/version api
wait_endpoint 'API metrics' http://127.0.0.1:8000/metrics api

bootstrap_url='http://127.0.0.1:8000/api/v1/customer/auth/browser-bootstrap'
assert_bootstrap_status(){
  local origin="$1" expected="$2" body_file="$tmp/bootstrap-body.json" status
  status="$(curl -sS -o "$body_file" -w '%{http_code}' -X POST "$bootstrap_url" \
    -H "Origin: $origin" -H 'X-VPN-Sale-Client: customer-web')"
  [[ "$status" == "$expected" ]]
  python3 - "$body_file" <<'PY'
import json,sys
body=json.load(open(sys.argv[1],encoding="utf-8"))
assert not ({"access_token","csrf_token","session_id"} & body.keys()), body
PY
}
assert_bootstrap_status 'https://app.dr-ping.com' 401
assert_bootstrap_status 'https://admin.dr-ping.com' 403
assert_bootstrap_status 'https://reseller.dr-ping.com' 403
printf 'customer bootstrap Origin boundary confirmed\n'

curl -fsS -o /dev/null -X OPTIONS "$bootstrap_url" \
  -H 'Origin: https://app.dr-ping.com' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: X-VPN-Sale-Client,X-CSRF-Token'
curl -fsS -o /dev/null -X OPTIONS \
  'http://127.0.0.1:8000/api/v1/admin/configuration/drafts/example/sections' \
  -H 'Origin: https://admin.dr-ping.com' \
  -H 'Access-Control-Request-Method: PATCH' \
  -H 'Access-Control-Request-Headers: Authorization,Content-Type,X-CSRF-Token,X-Request-ID'
printf 'customer POST and admin PATCH preflights confirmed\n'

capabilities="$(curl -fsS 'http://127.0.0.1:8000/api/v1/customer/auth/capabilities')"
python3 - "$capabilities" <<'PY'
import json,sys
body=json.loads(sys.argv[1])
assert body["public_registration"] is False, body
assert body["password_login"] is False, body
assert body["telegram_linking"] is False, body
assert body["web_credential_enrollment"] is False, body
PY
printf 'registration and password login defaults confirmed disabled\n'
for route in telegram-link/challenge telegram-link/complete telegram-link/unlink account-credentials/enroll; do
  headers="$tmp/linking-headers.txt"; body="$tmp/linking-body.json"
  status="$(curl -sS -D "$headers" -o "$body" -w '%{http_code}' -X POST \
    "http://127.0.0.1:8000/api/v1/customer/auth/$route" \
    -H 'Content-Type: application/json' --data '{}')"
  [[ "$status" == 404 ]]
  ! grep -Eiq '^set-cookie:' "$headers"
  ! grep -Eiq 'password|credential|access_token|refresh_token|csrf_token' "$body"
done
printf 'unified-account routes confirmed disabled without cookies or credentials\n'
wait_endpoint 'Customer web' http://127.0.0.1:3000 customer
wait_endpoint 'Admin web' http://127.0.0.1:3001 admin
wait_endpoint 'Reseller web' http://127.0.0.1:3002 reseller
assert_compose_service_not_restarted api "${compose[@]}"
printf 'API restart count confirmed\n'
"${compose[@]}" config --format json | python3 -c 'import json,sys
c=json.load(sys.stdin); expected={"api":[("127.0.0.1",8000)],"customer":[("127.0.0.1",3000)],"admin":[("127.0.0.1",3001)],"reseller":[("127.0.0.1",3002)],"postgres":[],"redis":[]}
actual={name:[(p.get("host_ip"),int(str(p["published"]))) for p in svc.get("ports",[])] for name,svc in c["services"].items()}
assert actual == expected, (actual,expected)'
printf 'port isolation confirmed\n'
printf 'restrictive image and real-stack acceptance passed\n'
