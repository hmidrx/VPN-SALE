# VPN-SALE Codespaces Development Container

This dev container is the browser-based Milestone 0 development environment. It is designed so contributors do not need Python, Node, npm, PostgreSQL, Redis, or Docker installed on a local computer.

## Included tools

- Ubuntu 24.04 base image
- Python 3.12
- Node.js 22 and npm
- Git and GitHub CLI
- Docker CLI and Docker Compose v2 through the maintained Docker-in-Docker devcontainer feature
- curl, jq, PostgreSQL client, and Redis client through the base image/features and bootstrap process
- Recommended VS Code extensions for Python, Ruff, Docker, GitHub Actions, YAML, Tailwind, and frontend editing

## First start

Codespaces runs this safe setup command after container creation:

```bash
bash scripts/bootstrap-dev.sh
```

The script creates `.venv`, installs Python and npm dependencies, copies `.env.example` to `.env` only when `.env` is absent, validates Docker availability, and prints next commands. It never commits files and never overwrites `.env`.

## Lockfile

The first successful bootstrap may create `package-lock.json` because the repository initially supports a temporary no-lockfile state. Review and commit it with:

```bash
git add package-lock.json
git commit -m "Add reproducible frontend dependency lockfile"
git push
```

After that, CI and Codespaces will prefer `npm ci`.

## Common commands

```bash
scripts/verify-backend.sh
scripts/verify-frontend.sh
scripts/verify-docker.sh
scripts/verify-all.sh
docker compose up --build api reverse-proxy
docker compose down --volumes --remove-orphans
```

The VS Code task runner exposes the same commands from the browser UI.

## Ports

- 8080: reverse proxy
- 8000: API
- 3000: customer web
- 3001: admin web
- 3002: reseller web
- 5432: PostgreSQL development access
- 6379: Redis development access

Do not add real panel, payment, Telegram, or production secrets to this Codespace.
