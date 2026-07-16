# Deployment

Deployment is Docker-first with PostgreSQL, Redis, reverse proxy, metrics, logs, backups, environment validation, secret management, CI gates, staging before production, and rollback via image/database migration discipline.

## Milestone 0 GitHub environments

Milestone 0 does not deploy production services. It provides:

- GitHub Actions verification on `ubuntu-latest` with read-only repository permissions.
- GitHub Codespaces for browser-based development with Python 3.12, Node.js 22, npm, Docker-in-Docker, PostgreSQL client, Redis client, curl, jq, Git, and GitHub CLI.
- Docker Compose validation and smoke testing for PostgreSQL, Redis, API, and reverse proxy in CI.

Codespaces and CI use safe development or CI-only placeholders and must not require Telegram, panel, payment, email, production domain, or customer data credentials.

## Milestone 1B-A bootstrap and key rotation

Run `python -m platform_api.cli bootstrap-admin --email admin@example.com` once after migrations. Use the interactive no-echo prompt, or `--password-stdin` only in protected automation. Recovery from lost Super Admin access is an operational database recovery with audited credential reset by trusted operators; no unsafe override flag is provided.

Rotate admin access-token signing keys by publishing a new key ID/value, accepting the previous key for at most the access-token lifetime, and then removing it. Rotate identity encryption keys by keeping old versions readable while writing new encrypted TOTP secrets with the new version.
