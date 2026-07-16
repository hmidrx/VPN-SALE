# Deployment

Deployment is Docker-first with PostgreSQL, Redis, reverse proxy, metrics, logs, backups, environment validation, secret management, CI gates, staging before production, and rollback via image/database migration discipline.

## Milestone 0 GitHub environments

Milestone 0 does not deploy production services. It provides:

- GitHub Actions verification on `ubuntu-latest` with read-only repository permissions.
- GitHub Codespaces for browser-based development with Python 3.12, Node.js 22, npm, Docker-in-Docker, PostgreSQL client, Redis client, curl, jq, Git, and GitHub CLI.
- Docker Compose validation and smoke testing for PostgreSQL, Redis, API, and reverse proxy in CI.

Codespaces and CI use safe development or CI-only placeholders and must not require Telegram, panel, payment, email, production domain, or customer data credentials.
