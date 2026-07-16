# Milestone 1B-A Plan: Administrator Authentication Backend

## Scope
Backend-only administrator authentication: first Super Admin bootstrap, password login, short-lived signed access tokens, opaque refresh-token cookies, server-side administrator sessions, refresh rotation/reuse detection, TOTP MFA, one-time recovery codes, CSRF state, rate limiting, and audit/security events.

## Non-goals
Customer auth, Telegram auth, bot registration, commerce, wallets, orders, payments, panels, provisioning, subscriptions, tickets, marketing, full admin-management APIs, RBAC-management APIs, and complete frontend pages remain out of scope.

## Threat assumptions
Attackers may attempt credential stuffing, account enumeration, stolen refresh-token replay, CSRF against cookie endpoints, TOTP/recovery-code replay, log scraping, and database read-only compromise. Raw passwords, refresh tokens, MFA challenges, TOTP secrets, recovery codes, and CSRF secrets must never be logged or stored in plaintext.

## API decisions
Versioned endpoints live under `/api/v1/admin/auth/...`. Routes are thin FastAPI adapters calling application services. External authentication errors are generic; internal audit and security events record safe reason codes.

## Session strategy
Access credentials are short-lived HS256 JWTs with issuer, audience, subject, session ID, JTI, issued-at, expiry, algorithm allowlist, and key ID. Refresh credentials are opaque random values stored only as salted SHA-256 hashes in server-side `admin_sessions`. Refresh rotation creates a new generation and marks the previous generation consumed. Reuse of consumed credentials revokes the full session family.

## Acceptance criteria
- First Super Admin bootstrap is explicit, transactional, idempotently seeds RBAC, and refuses a second active Super Admin.
- Login prevents enumeration, enforces status/lockout/rate limits, and creates sessions only after all factors succeed.
- TOTP enrollment requires confirmation and recovery codes are shown once and stored only as hashes.
- Refresh rotation, reuse detection, logout, session revocation, CSRF state, and audit/security events are covered by tests.
