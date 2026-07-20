# Test server deployment

This runbook installs the VPN-SALE test stack on a disposable Ubuntu 24.04 host from `main`. It is intentionally conservative: it does not install UFW, does not expose PostgreSQL or Redis, does not touch unrelated hostnames such as `fast.dr-ping.com`, and never deletes volumes during normal installs or upgrades.

## DNS prerequisites

Create A/AAAA records for the target server only:

- `app.<domain>`
- `api.<domain>`
- `admin.<domain>`
- `reseller.<domain>`

Do not change unrelated records. Ports 80 and 443 must be free so Caddy can obtain HTTPS certificates.

## Fresh install from main

Run as root on Ubuntu 24.04:

```bash
curl -fsSL https://raw.githubusercontent.com/hmidrx/VPN-SALE/main/scripts/install-test-server.sh -o /root/install-test-server.sh
chmod 700 /root/install-test-server.sh
/root/install-test-server.sh --domain example.com
```

The installer clones `https://github.com/hmidrx/VPN-SALE.git`, deploys `main`, generates missing secrets in `/opt/vpn-sale-runtime/test.env` with mode `0600`, installs Docker Engine, the current Docker Compose plugin, Caddy, Fail2ban, and required utilities including `jq`, `ripgrep`, `nodejs`, and `npm`, builds images, runs Alembic migrations once, starts the API and web apps, configures Caddy, and runs smoke tests.

## Interactive Telegram setup

Use `--enable-telegram` and enter the token at the secure no-echo prompt:

```bash
/root/install-test-server.sh --domain example.com --enable-telegram
```

The installer verifies the token with Telegram `getMe`, derives the bot username, removes any webhook before polling, configures commands, sets the default Web App menu button to `https://app.example.com`, and starts the repository polling bot.

## Non-interactive token-file setup

Store the token in a protected file; do not pass secrets on the command line:

```bash
install -m 0600 /dev/null /root/vpn-sale-telegram.token
printf '%s' 'REDACTED_TOKEN_FROM_BOTFATHER' >/root/vpn-sale-telegram.token
/root/install-test-server.sh \
  --domain example.com \
  --enable-telegram \
  --telegram-bot-token-file /root/vpn-sale-telegram.token \
  --non-interactive
```

## Safe rerun and upgrade

Normal reruns preserve generated secrets and PostgreSQL/Redis data. Docker Compose `ps --format json` output is normalized for both current JSON Lines output and legacy JSON arrays before health checks, so no Docker Compose downgrade or pin is required. If a previous incomplete run already installed the repository-managed Caddy configuration, reruns recognize the `# vpn-sale-test-server-managed` Caddyfile marker and reconfigure that Caddy service instead of treating it as an unknown port conflict. The installer still refuses unmanaged listeners on ports 80/443 and never stops unrelated processes. To upgrade safely from `main`:

```bash
cd /opt/vpn-sale
git fetch origin main
git checkout main
git merge --ff-only origin/main
/opt/vpn-sale/scripts/install-test-server.sh --domain example.com
```

For Telegram deployments, include the same Telegram flags used during installation. Advanced branch testing may use `--ref some-branch`, but normal installation and upgrades should use `main`.

## Smoke tests

The installer runs smoke tests automatically. You can rerun them manually:

```bash
VPN_SALE_TEST_SERVER_ENV_FILE=/opt/vpn-sale-runtime/test.env \
VPN_SALE_TEST_SERVER_DOMAIN=example.com \
/opt/vpn-sale/scripts/smoke-test-test-server.sh
```

Smoke tests validate database/Redis health using the same Compose JSON normalization helper, API `/health` and `/ready`, local web HTTP, public HTTPS endpoints, certificates, absence of public database/cache bindings, zero restart loops, current Alembic revision, frontend build-time bot configuration, Telegram state when enabled, and secret-free reports.

## Disposable reset warning

Never reset data during a normal install or upgrade. The only destructive database action is explicit and disposable:

```bash
/opt/vpn-sale/scripts/install-test-server.sh --domain example.com --reset-disposable-postgres
```

This resets only the disposable PostgreSQL volume. Redis data is never deleted automatically, and the installer never removes Compose volumes during normal operation.

## Troubleshooting without revealing secrets

Use commands that avoid printing the env file:

```bash
docker compose --project-directory /opt/vpn-sale -f /opt/vpn-sale/docker-compose.yml -f /opt/vpn-sale/docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env ps
journalctl -u caddy --no-pager -n 80
docker compose --project-directory /opt/vpn-sale -f /opt/vpn-sale/docker-compose.yml -f /opt/vpn-sale/docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env logs api --tail=80 | sed -E 's/(TOKEN|PASSWORD|SECRET|KEY)=([^[:space:]]+)/\1=<redacted>/g'
caddy validate --config /etc/caddy/Caddyfile
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
```
