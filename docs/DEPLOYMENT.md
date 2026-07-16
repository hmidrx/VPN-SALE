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

## Milestone 1B-B lifecycle

The API creates a cached synchronous SQLAlchemy engine from the configured database URL and provides one request-scoped session with rollback on failure and close after completion. Production-like environments must provide identity encryption, admin access-token signing, and CSRF secrets explicitly; insecure production cookie settings are rejected during startup.

## Milestone 1C-A customer authentication note
Customer Telegram Mini App authentication now verifies raw init data, links Telegram identities to internal customers, issues isolated customer access credentials, rotates opaque refresh-cookie sessions, enforces CSRF on cookie-authenticated state changes, rate limits sensitive operations, and records sanitized audit/security events. Commerce and customer UI remain out of scope.
## Milestone 1C-B1 frontend configuration
Customer deployments may set `NEXT_PUBLIC_CUSTOMER_API_BASE_URL`, `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME`, and `NEXT_PUBLIC_CUSTOMER_APP_NAME`. `NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM=true` is development/test only and production builds reject it. No bot token or signing key is exposed to frontend variables.
