#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; tmp="$(mktemp -d)"; project="vpn-sale-acceptance-$$"; trap 'docker compose -p "$project" -f "$tmp/docker-compose.yml" down -v --remove-orphans >/dev/null 2>&1 || true; chmod -R u+rwX "$tmp"; rm -rf "$tmp"' EXIT
# Archive only tracked content, then reproduce the 0700/0600 host checkout.
tar -C "$repo_root" --exclude=.git --exclude=node_modules --exclude=.next -cf - . | tar -C "$tmp" -xf -
find "$tmp" -type d -exec chmod 0700 {} +; find "$tmp" -type f -exec chmod 0600 {} +; while IFS= read -r -d '' f; do chmod 0700 "$tmp/$f"; done < <(git -C "$repo_root" ls-files -z '*.sh')
cd "$tmp"
docker build -f infra/docker/api.Dockerfile -t "$project-api" .
docker build -f infra/docker/worker.Dockerfile -t "$project-worker" .
docker build -f infra/docker/telegram-bot.Dockerfile -t "$project-telegram" .
for app in customer-web admin-web reseller-web; do docker build -f infra/docker/web.Dockerfile --build-arg APP_NAME="$app" --build-arg NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000 --build-arg NEXT_PUBLIC_CUSTOMER_API_BASE_URL=http://127.0.0.1:8000 --build-arg NEXT_PUBLIC_TELEGRAM_BOT_USERNAME=disabled_bot --build-arg NEXT_PUBLIC_CUSTOMER_APP_NAME=Test -t "$project-$app" .; done
docker run --rm "$project-api" sh -ec 'test "$(id -u)" != 0; test -r /app/apps/api/alembic.ini; find /app/apps/api/alembic/versions -type f -readable | grep -q .; python -c "from platform_api.main import app; assert app"; alembic --version'
for image in worker telegram customer-web admin-web reseller-web; do docker run --rm --entrypoint sh "$project-$image" -ec 'test "$(id -u)" != 0'; done
cat >docker-compose.yml <<YAML
services:
  postgres:
    image: postgres:16
    environment: {POSTGRES_USER: vpnsale, POSTGRES_PASSWORD: acceptance_password, POSTGRES_DB: vpnsale}
    healthcheck: {test: [CMD-SHELL, "pg_isready -U vpnsale"], interval: 2s, timeout: 2s, retries: 30}
  redis:
    image: redis:7
    healthcheck: {test: [CMD, redis-cli, ping], interval: 2s, timeout: 2s, retries: 30}
  api:
    image: $project-api
    environment: &env
      VPN_SALE_ENVIRONMENT: test
      VPN_SALE_VERSION: acceptance
      VPN_SALE_DATABASE_URL: postgresql+asyncpg://vpnsale:acceptance_password@postgres:5432/vpnsale
      DATABASE_URL: postgresql+asyncpg://vpnsale:acceptance_password@postgres:5432/vpnsale
      VPN_SALE_SYNC_DATABASE_URL: postgresql://vpnsale:acceptance_password@postgres:5432/vpnsale
      VPN_SALE_REDIS_URL: redis://redis:6379/0
      VPN_SALE_IDENTITY_ENCRYPTION_KEY: acceptance-only-identity-key-00000000000000000000000000000000
      VPN_SALE_IDENTITY_ENCRYPTION_KEY_VERSION: acceptance-v1
      VPN_SALE_ADMIN_ACCESS_TOKEN_SIGNING_KEY: acceptance-only-admin-signing-key-00000000000000000000000000
      VPN_SALE_CUSTOMER_ACCESS_TOKEN_SIGNING_KEY: acceptance-only-customer-signing-key-00000000000000000000
      VPN_SALE_ADMIN_CSRF_SECRET: acceptance-only-admin-csrf-000000000000000000000000000000
      VPN_SALE_CUSTOMER_CSRF_SECRET: acceptance-only-customer-csrf-00000000000000000000000000
      VPN_SALE_PROVIDER_WRITES_ENABLED: "false"
      VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED: "false"
      VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED: "false"
    ports: ["127.0.0.1:8000:8000"]
    depends_on: {postgres: {condition: service_healthy}, redis: {condition: service_healthy}}
  customer: {image: $project-customer-web, ports: ["127.0.0.1:3000:3000"]}
  admin: {image: $project-admin-web, ports: ["127.0.0.1:3001:3000"]}
  reseller: {image: $project-reseller-web, ports: ["127.0.0.1:3002:3000"]}
YAML
docker compose -p "$project" up -d postgres redis
docker compose -p "$project" run --rm api alembic -c /app/apps/api/alembic.ini upgrade head
docker compose -p "$project" run --rm api alembic -c /app/apps/api/alembic.ini upgrade head
docker compose -p "$project" run --rm api alembic -c /app/apps/api/alembic.ini current | grep -q '(head)'
docker compose -p "$project" up -d api customer admin reseller
for url in http://127.0.0.1:8000/health http://127.0.0.1:8000/ready http://127.0.0.1:8000/version http://127.0.0.1:3000 http://127.0.0.1:3001 http://127.0.0.1:3002; do "$tmp/scripts/wait-for-http.sh" "$url" 120; done
# Exact isolation: only six expected loopback bindings; DB/cache have none.
docker compose -p "$project" config --format json | python3 -c 'import json,sys
c=json.load(sys.stdin); expected={"api":[("127.0.0.1",8000)],"customer":[("127.0.0.1",3000)],"admin":[("127.0.0.1",3001)],"reseller":[("127.0.0.1",3002)],"postgres":[],"redis":[]}
actual={name:[(p.get("host_ip"),int(p["published"])) for p in svc.get("ports",[])] for name,svc in c["services"].items()}
assert actual == expected, (actual,expected)'
printf 'restrictive image and real-stack acceptance passed\n'
