# Observability

Observability includes structured logs, correlation/request/trace IDs, metrics, error tracking, audit logs, health/readiness/dependency health, worker metrics, queue depth, payment/provisioning/panel/notification metrics, and business KPIs without secrets.

## Milestone 1B-A authentication events

Administrator bootstrap, login success/failure/lockout/rate-limit, MFA enrollment/challenge/success/failure, recovery-code use/regeneration, session create/refresh/revoke, refresh reuse, and password change events are audit/security event candidates. Metadata must remain sanitized and free of passwords, token values, token hashes, TOTP values, recovery codes, and CSRF secrets.

## Milestone 1B-B auth signals

Structured audit/security events now include session revocation, password change, recovery-code regeneration, MFA disablement, refresh reuse, and CSRF/rate-limit rejection candidates. Metric labels must use safe event codes only and must not include email addresses, raw IPs, user agents, tokens, codes, or secrets.

## Milestone 1C-A customer authentication note
Customer Telegram Mini App authentication now verifies raw init data, links Telegram identities to internal customers, issues isolated customer access credentials, rotates opaque refresh-cookie sessions, enforces CSRF on cookie-authenticated state changes, rate limits sensitive operations, and records sanitized audit/security events. Commerce and customer UI remain out of scope.
## Milestone 1C-B1 frontend diagnostics
Customer frontend diagnostics are limited to safe state names, safe error codes, correlation IDs, and timings in development/test. Raw init data, access tokens, refresh tokens, CSRF tokens, Telegram payloads, Telegram IDs, names, and full API bodies are not logged.
