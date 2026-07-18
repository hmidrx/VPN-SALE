# VPN-SALE disposable test-server deployment

This guide is for one Ubuntu 24.04 non-production integration server. It is not a production deployment: no VPN panel is installed, provider writes remain disabled, no real payment gateway is active, polling is only for this disposable test server, and UFW is outside this repository and not required.

## Fresh clone and runtime environment

```bash
git clone <repo-url> VPN-SALE
cd VPN-SALE
mkdir -p /opt/vpn-sale-runtime /var/lib/vpn-sale/backups/test-server
cp infra/deployment/env/test-server.env.example /opt/vpn-sale-runtime/test.env
chmod 600 /opt/vpn-sale-runtime/test.env
```

Generate placeholders without printing them into shell history where possible:

```bash
python3 - <<'PY'
import base64, secrets
for name in ["POSTGRES_PASSWORD", "IDENTITY_ENCRYPTION_KEY", "ADMIN_ACCESS_TOKEN_SIGNING_KEY", "CUSTOMER_ACCESS_TOKEN_SIGNING_KEY", "ADMIN_CSRF_SECRET", "CUSTOMER_CSRF_SECRET", "TELEGRAM_RATE_LIMIT_KEY"]:
    print(name, base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())
PY
```

Edit `/opt/vpn-sale-runtime/test.env`. Set `VPN_SALE_BOT_ENABLED=true` and `VPN_SALE_BOT_MODE=polling` only after a real test bot token and BotFather Mini App URL are configured. Do not commit this file.

Changing any `NEXT_PUBLIC_*` value requires rebuilding frontend images because Next.js embeds public variables at build time.

## Compose validation and sequential builds

Use sequential builds on a 2 CPU / 4 GB host:

```bash
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env config
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env build --progress=plain api
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env build --progress=plain worker
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env build --progress=plain telegram-bot
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env build --progress=plain customer-web
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env build --progress=plain admin-web
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env build --progress=plain reseller-web
```

## Database, Redis, migrations, and API

```bash
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env run --rm api alembic -c apps/api/alembic.ini heads
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env run --rm api alembic -c apps/api/alembic.ini upgrade head
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env up -d api worker
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env run --rm api python -m platform_api.cli bootstrap-admin --email admin@example.invalid
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env exec api python -c "import urllib.request; [print(u, urllib.request.urlopen('http://127.0.0.1:8000'+u, timeout=3).status) for u in ['/health','/ready','/version']]"
```

The bootstrap command prompts for the password interactively; do not put a Super Admin password on the command line.

## Web and Telegram startup

```bash
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env up -d customer-web admin-web reseller-web
# After configuring the test bot token and polling mode in /opt/vpn-sale-runtime/test.env:
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env --profile telegram up -d telegram-bot
```

BotFather setup: set the Mini App URL to `https://app.dr-ping.com`. The bot validates that `VPN_SALE_CUSTOMER_MINI_APP_URL` uses the allowlisted host `app.dr-ping.com`, processes `/start`, shows the existing Persian menu, and does not create fake browser sessions or require a provider panel.

## Host Caddy and HTTPS verification

Install Caddy on the host by your normal operations process, then adapt `infra/deployment/test-server/Caddyfile.example` to `/etc/caddy/Caddyfile`.

```bash
curl -fsS https://api.dr-ping.com/health
curl -fsS https://api.dr-ping.com/ready
curl -fsS https://api.dr-ping.com/version
curl -I https://app.dr-ping.com
curl -I https://admin.dr-ping.com
curl -I https://reseller.dr-ping.com
curl -I https://sub.dr-ping.com/subscriptions
curl -I https://status.dr-ping.com/health
```

The example routes `sub.dr-ping.com` and `status.dr-ping.com` as complete hostnames to the API because the application is not host-aware. It blocks public `/metrics`, preserves forwarded host/proto headers, supports HTTP upgrade behavior through Caddy's reverse proxy defaults, and applies no-store headers to avoid caching authenticated responses.

## Smoke tests, logs, stop, restart, and reset

```bash
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env ps
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env logs --tail=100 api worker customer-web admin-web reseller-web
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env stop
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env up -d postgres redis api worker customer-web admin-web reseller-web
# Disposable database reset only; removes the test PostgreSQL volume, not source files.
docker compose -f docker-compose.yml -f docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env down
docker volume rm vpn-sale_test_server_postgres_data
```

Do not run `git push` from the test server guide. Real payment gateways, public fake-success payments, provider panels, Xray, and provider write containers are intentionally absent.
