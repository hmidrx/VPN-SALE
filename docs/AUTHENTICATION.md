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
