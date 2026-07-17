# Authentication

Customer auth will support Telegram Mini App init data verification, Telegram website login, optional email/passwordless identity, session history, and revocation. Admin auth will use email/password with Argon2id, optional/required TOTP, backup codes, refresh rotation, trusted devices, IP allowlists, and brute-force protection.

## Milestone 1A foundation

Milestone 1A implements only the data and cryptographic foundations for later authentication. User statuses are `PENDING`, `ACTIVE`, `SUSPENDED`, `BLOCKED`, and `DEACTIVATED`; admin statuses are `INVITED`, `ACTIVE`, `LOCKED`, and `DISABLED`. Legal transitions are explicit and reject undocumented moves. Password hashing uses Argon2id with configurable time, memory, and parallelism parameters. Refresh-token persistence stores only opaque token hashes and session lineage metadata; no login or refresh endpoint is implemented.

## Milestone 1B-A administrator authentication

Administrators are bootstrapped explicitly with `python -m platform_api.cli bootstrap-admin --email <address>` and a no-echo password prompt, or `--password-stdin` for CI tests. The command seeds RBAC, assigns `super_admin`, rejects duplicate active Super Admin bootstrap, and does not print credentials or MFA material.

Admin login uses normalized email lookup, Argon2id verification, generic external errors, failed-login counters, lockout, and keyed rate-limit identifiers. Successful password authentication creates a session immediately only when MFA is not enabled. When TOTP is enabled, the password step returns an opaque short-lived MFA challenge; a session is created only after TOTP or a recovery code succeeds.

Refresh rotation uses opaque refresh credentials in an HttpOnly cookie and stores only hashes. Reusing a consumed refresh credential revokes the session family and records audit/security events.

```mermaid
sequenceDiagram
  participant A as Admin
  participant API
  participant DB
  A->>API: email + password
  API->>DB: verify admin/password/status
  API->>DB: create admin_session
  API-->>A: access token + HttpOnly refresh cookie + CSRF token
```

```mermaid
sequenceDiagram
  participant A as Admin
  participant API
  participant DB
  A->>API: email + password
  API->>DB: verify password and active TOTP
  API->>DB: store hashed MFA challenge
  API-->>A: MFA_REQUIRED + challenge
  A->>API: challenge + TOTP/recovery code
  API->>DB: consume challenge and verify factor
  API->>DB: create admin_session
  API-->>A: access token + refresh cookie
```

```mermaid
sequenceDiagram
  participant A as Admin
  participant API
  participant DB
  A->>API: refresh cookie + CSRF token
  API->>DB: find active session generation
  API->>DB: mark old generation consumed
  API->>DB: create next generation with new hash
  API-->>A: new access token + rotated refresh cookie
```

```mermaid
sequenceDiagram
  participant X as Attacker
  participant API
  participant DB
  X->>API: consumed refresh token
  API->>DB: detect consumed generation
  API->>DB: revoke full session family
  API->>DB: write high-value events
  API-->>X: generic authentication failure
```

```mermaid
sequenceDiagram
  participant A as Admin
  participant API
  participant DB
  A->>API: begin TOTP enrollment
  API->>DB: store encrypted pending secret
  API-->>A: otpauth URI
  A->>API: confirmation TOTP code
  API->>DB: activate credential and store recovery hashes
  API-->>A: plaintext recovery codes once
```

```mermaid
sequenceDiagram
  participant A as Admin
  participant API
  participant DB
  A->>API: logout/revoke session
  API->>DB: mark session revoked
  API-->>A: delete refresh cookie
```

## Milestone 1B-B completed admin endpoint inventory

The administrator auth API now includes typed endpoints for login, MFA challenge verification, refresh, CSRF state, current profile, session listing, logout, selected-session revocation, revoke-all-other sessions, revoke-all sessions, password change, TOTP enrollment/confirmation, recovery-code regeneration, and MFA disablement.

Browser clients keep access tokens in memory only, send them with `Authorization`, and rely on the refresh credential only through the HttpOnly refresh cookie. Cookie-authenticated state-changing endpoints require `X-CSRF-Token`; the token is bound to the server-side admin session and rotates with refresh generations.

## Milestone 1C-A customer Telegram authentication
Customer Telegram Mini App authentication accepts only the raw init-data query string and verifies it server-side with the configured bot token. The verifier rejects malformed percent encoding, duplicate keys, missing hash/auth_date/user, malformed JSON, invalid Telegram IDs, invalid signatures, expired data, future timestamps, and oversized payloads. Usernames are profile data only and are never identity keys.

First verified Telegram login creates an internal customer `User`, `CustomerProfile`, and `TelegramAccount`, then atomically activates the PENDING customer. ACTIVE customers may authenticate; SUSPENDED, BLOCKED, and DEACTIVATED customers receive generic authentication failures with safe internal event reason codes.

Customer access tokens use customer-only issuer and audience values. Refresh credentials are opaque HttpOnly cookies stored only as hashes in `customer_sessions`. Refresh rotation consumes the old generation, creates the next generation, rotates CSRF state, and revokes the family when a consumed token is reused.
## Milestone 1C-B1 customer frontend authentication
The customer frontend bootstraps only from raw Telegram Mini App `initData`, posts it once to `/api/v1/customer/auth/telegram-mini-app`, stores returned access credentials in memory only, loads `/me` and `/sessions`, and relies on the backend HttpOnly refresh cookie. Refresh requests include `credentials: "include"` and `X-CSRF-Token`; parallel refresh attempts are collapsed into one in-flight promise and authorized requests retry at most once. Browser users receive a fallback shell, not a fake login.

## Milestone 1C-B2 Telegram bot foundation
The Telegram bot foundation supports explicit disabled, polling and secure webhook modes. Disabled mode is the default for CI and Docker verification and performs no Telegram network calls. Polling is for local development only. Webhook mode requires an HTTPS base URL, an environment-only secret token validated with constant-time comparison, request-size limits, allowed update configuration and update-id idempotency.

The `/start` flow normalizes trusted Bot API identity fields and calls a typed `RegisterOrUpdateTelegramBotUser` application use case. It does not create a browser session; Mini App authentication continues to verify raw Telegram initData through the existing backend flow. Usernames are never identity keys, and internal user UUIDs remain independent from Telegram user IDs.

The customer menu is an extensible registry with Persian defaults and English fallback preparation. Current working destinations are Mini App home, profile, sessions/security, help, language and privacy/about. Future commerce modules must register commands and menu items through feature modules and must not place product, pricing, payment or provisioning rules inside bot handlers.

Mini App URLs are generated by a centralized allowlisted builder. Tokens, initData, Telegram IDs, usernames, emails and internal UUIDs are never placed in URLs. Callback data is compact, typed and versioned. Logs and metrics use low-cardinality outcome fields and forbid raw updates, message text, identity fields and secrets.

```mermaid
flowchart LR
  Telegram[Telegram bot] --> UseCase[Application use case]
  UseCase --> View[Safe customer view models]
  View --> Future[Future commerce/provisioning abstraction]
  Future --> Provider[Versioned provider adapters]
```

## Milestone 1D-A identity administration
Milestone 1D-A introduces backend-only management APIs protected by database-resolved permissions. Effective permissions are loaded from active role assignments for each protected request, disabled/locked administrators are denied immediately, and final active Super Admin safeguards prevent disabling or stripping the last privileged administrator path. Administrator invitations store only token hashes and return plaintext tokens once. Customer management uses documented status transitions and revokes sessions on sensitive restrictions. Audit logs are query-only and append-oriented; security events add acknowledgment/resolution workflow state. Management UI and all commerce/provider functionality remain out of scope.

## Milestone 1D-B identity administration frontend
The administrator frontend adds permission-aware identity management pages for administrators, invitations, roles, permissions, customers, sessions, audit logs, and security events. The UI consumes the existing management APIs, reuses memory-only access tokens, HttpOnly refresh cookies, CSRF headers, and single-flight refresh, and never becomes the authoritative authorization layer. Direct unauthorized routes must show controlled forbidden states while backend permission checks remain decisive.

Invitation tokens are displayed exactly once from ephemeral component state, are never placed in URLs, localStorage, sessionStorage, logs, or analytics, and are cleared after acknowledgment. Audit metadata rendering is defensive and suppresses secret-like keys. Session pages show only normalized safe metadata returned by the backend. The security center supports acknowledgment/resolution language without implying that acknowledgment removes the underlying event.

## Milestone 2-B2 customer storefront authentication
Storefront browsing runs after the existing Mini App bootstrap. Protected preview and quote creation require the existing customer access token, refresh single-flight and CSRF lifecycle. Browser fallback remains explicit; no fake login or auth bypass is introduced.
