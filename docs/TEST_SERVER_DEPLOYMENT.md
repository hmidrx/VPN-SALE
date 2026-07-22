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

## Hardened clean Ubuntu 24.04 test-server workflow

This TEST installer is designed for a completely rebuilt Ubuntu 24.04 host serving only these deployment names: `app.dr-ping.com`, `api.dr-ping.com`, `admin.dr-ping.com`, and `reseller.dr-ping.com`. The generated deployment configuration must not contain or affect `fast.dr-ping.com`.

### One-time private-repository bootstrap

Because `hmidrx/VPN-SALE` is private, first install a read-only deploy key or equivalent GitHub access for the server account. This bootstrap is intentionally separate from the installer and should not store production secrets in the repository or runtime env file.

### Required DNS

Before running the installer, point these records at the rebuilt server:

- `app.dr-ping.com`
- `api.dr-ping.com`
- `admin.dr-ping.com`
- `reseller.dr-ping.com`

Do not delegate or configure `fast.dr-ping.com` through this installer.

### Single installer invocation after deploy-key setup

```bash
curl -fsSL https://raw.githubusercontent.com/hmidrx/VPN-SALE/main/scripts/install-test-server.sh -o /root/install-test-server.sh
chmod 700 /root/install-test-server.sh
sudo /root/install-test-server.sh --domain dr-ping.com --repo git@github.com:hmidrx/VPN-SALE.git --ref main --non-interactive
```

To enable Telegram polling for TEST, provide a mode-`0600` token file and let the installer derive the public bot username from Telegram `getMe`:

```bash
install -m 0600 /dev/null /root/vpn-sale-telegram-token
# paste token with an editor that does not echo it in shell history
sudo /root/install-test-server.sh --domain dr-ping.com --repo git@github.com:hmidrx/VPN-SALE.git --ref main --enable-telegram --telegram-bot-token-file /root/vpn-sale-telegram-token --non-interactive
```

Interactive installs may omit `--telegram-bot-token-file`; the hidden prompt is read from `/dev/tty`, never from installer stdin or a heredoc.

### Runtime state, secrets, and safe reruns

Runtime files live under `/opt/vpn-sale-runtime` with restrictive permissions. The non-secret state file `/opt/vpn-sale-runtime/state.json` records TEST environment metadata, root domain, repository, selected ref/commit, compose project name, and the last completed phase. Plaintext generated secrets are stored separately in mode-`0600` files under `/opt/vpn-sale-runtime/secrets` and are copied into `/opt/vpn-sale-runtime/test.env` without printing values.

Secrets are generated exactly once. On rerun, the installer reuses existing secret files and rebuilds the runtime env file from those preserved sources. If the deployment PostgreSQL volume already exists but `/opt/vpn-sale-runtime/secrets/postgres-password` is missing, empty, or not mode `0600`, the installer stops with a state-mismatch error instead of generating a replacement password or modifying database roles.

### Interruption recovery

The installer writes state atomically after each major phase and makes every wait bounded with concise redacted diagnostics. A normal rerun resumes safely after package installation, env creation, PostgreSQL initialization, or Caddy installation. It never runs broad Compose volume teardown, never resets PostgreSQL automatically, and never deletes Redis during PostgreSQL recovery.

### Explicit TEST-only PostgreSQL reset

For this disposable TEST deployment only, reset PostgreSQL explicitly:

```bash
sudo /opt/vpn-sale/scripts/install-test-server.sh --domain dr-ping.com --repo git@github.com:hmidrx/VPN-SALE.git --ref main --reset-disposable-postgres --non-interactive
```

The installer prints the exact PostgreSQL container and volume names before removal, removes only that PostgreSQL container and PostgreSQL volume, preserves Redis and all non-database generated secrets, and refuses to trigger this behavior implicitly.

### PostgreSQL identity and migrations

The TEST deployment uses the configured `POSTGRES_USER` and `POSTGRES_DB` (default `vpnsale`) for readiness checks, migrations, diagnostics, and application connections. It does not assume that a `postgres` role exists, because the official PostgreSQL image initializes the configured administrative role when `POSTGRES_USER` is set. Raw `POSTGRES_PASSWORD` remains separate from URL values; the installer percent-encodes it once for SQLAlchemy URLs, and Alembic escapes percent signs before assigning `sqlalchemy.url`.

### Caddy ownership and rerun behavior

The installer configures the official Caddy Debian/Ubuntu APT repository using the Cloudsmith `gpg.key` and `debian.deb.txt` endpoints. It installs prerequisite keyring/HTTPS packages first, writes only `/usr/share/keyrings/caddy-stable-archive-keyring.gpg` and `/etc/apt/sources.list.d/caddy-stable.list` with temporary files plus atomic renames, keeps both files mode `0644`, never uses `apt-key`, and leaves unrelated APT repositories and trusted keys untouched. `apt-get update` runs only after both Caddy repository files are in place; if the Caddy repository reports `NO_PUBKEY`, the installer refreshes its managed keyring and retries exactly once without disabling signature verification.

The installer performs port preflight before package installation where possible. After the Caddy package is installed, it immediately stops `caddy.service` only when the service is proven to be either installer-managed (`# vpn-sale-test-server-managed`) or still using the untouched package-default Caddyfile. It rejects unrelated listeners on ports 80/443 and does not rely only on the process name. Managed Caddy configuration is validated with `caddy validate`, contains only the four required host blocks, preserves forwarding headers, blocks public metrics/internal diagnostic paths, and is activated only after application services are ready.

### Post-install verification

Run the safe verifier after installation or rerun:

```bash
sudo /opt/vpn-sale/scripts/verify-test-server.sh --domain dr-ping.com --env-file /opt/vpn-sale-runtime/test.env
```

The verifier checks the repository commit, Compose rendering, expected services and profiles, PostgreSQL and Redis health, migration state, API readiness, local web HTTP bindings, managed Caddy ownership of ports 80/443, loopback-only application ports, no public PostgreSQL/Redis/worker/Telegram ports, HTTPS for all four domains, optional Telegram polling container identity, fail2ban, swap, and absence of `fast.dr-ping.com` from generated deployment configuration without exposing secrets.
