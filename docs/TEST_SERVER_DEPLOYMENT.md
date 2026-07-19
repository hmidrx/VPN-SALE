# Test server deployment

Use the repository installer for disposable Ubuntu 24.04 integration servers. The test server does **not** install a VPN panel, Xray, 3X-UI, real payment gateways, provider-write services, or UFW.

## Fresh install

Point DNS for `app.<domain>`, `api.<domain>`, `admin.<domain>`, and `reseller.<domain>` to the server, then run as root:

```bash
curl -fsSL https://raw.githubusercontent.com/hmidrx/VPN-SALE/fix/deployment-hardening/scripts/install-test-server.sh -o /root/install-test-server.sh
bash /root/install-test-server.sh --domain example.com --repo https://github.com/hmidrx/VPN-SALE.git --ref fix/deployment-hardening --enable-telegram
```

The installer writes protected runtime configuration to `/opt/vpn-sale-runtime/test.env` with mode `0600`, derives public origins from `--domain`, URL-encodes the PostgreSQL password in application URLs, and verifies the Compose model before service changes. It never prints passwords, bot tokens, or full database URLs.

## Rerun / upgrade

```bash
/opt/vpn-sale/scripts/install-test-server.sh --domain example.com --repo https://github.com/hmidrx/VPN-SALE.git --ref fix/deployment-hardening --runtime-dir /opt/vpn-sale-runtime
```

The Compose wrapper is:

```bash
/opt/vpn-sale/scripts/vpn-sale-compose-test-server --env-file /opt/vpn-sale-runtime/test.env ps
```

It runs Docker Compose with a clean environment so exported shell variables cannot override the runtime env file.

## Telegram rotation

Update only `VPN_SALE_TELEGRAM_BOT_TOKEN` and `VPN_SALE_TELEGRAM_BOT_USERNAME` in `/opt/vpn-sale-runtime/test.env`, then rerun the installer with `--enable-telegram` or restart the opt-in Telegram profile. Production-like polling restrictions remain enforced; this disposable deployment uses `VPN_SALE_ENVIRONMENT=TEST`.

## Disposable PostgreSQL reset

Existing PostgreSQL data is not silently deleted. Use the explicit flag only for disposable test data:

```bash
/opt/vpn-sale/scripts/install-test-server.sh --domain example.com --reset-disposable-postgres
```

The Redis volume is not part of PostgreSQL repair.

## Smoke checks and diagnostics

```bash
/opt/vpn-sale/scripts/smoke-test-test-server.sh
/opt/vpn-sale/scripts/verify-test-server-compose.sh /opt/vpn-sale-runtime/test.env
journalctl -u caddy --no-pager -n 100
docker compose --project-directory /opt/vpn-sale -f /opt/vpn-sale/docker-compose.yml -f /opt/vpn-sale/docker-compose.test-server.yml --env-file /opt/vpn-sale-runtime/test.env ps
```

Safe checks include API `/health`, `/ready`, `/version`, local web ports, Caddy validation, no public PostgreSQL/Redis ports, worker absence by default, and Telegram restart counts when enabled.

## Limitations

This deployment is for integration testing only: no provider panel, no Xray/3X-UI, no real payment gateway, no provider writes, and no changes to any `fast.<domain>` host.
