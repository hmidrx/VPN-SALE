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
