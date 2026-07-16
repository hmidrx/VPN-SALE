# Observability

Observability includes structured logs, correlation/request/trace IDs, metrics, error tracking, audit logs, health/readiness/dependency health, worker metrics, queue depth, payment/provisioning/panel/notification metrics, and business KPIs without secrets.

## Milestone 1B-A authentication events

Administrator bootstrap, login success/failure/lockout/rate-limit, MFA enrollment/challenge/success/failure, recovery-code use/regeneration, session create/refresh/revoke, refresh reuse, and password change events are audit/security event candidates. Metadata must remain sanitized and free of passwords, token values, token hashes, TOTP values, recovery codes, and CSRF secrets.
