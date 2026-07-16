# Milestone 1C-A Plan: Telegram Customer Authentication Backend

## Scope
Milestone 1C-A implements backend-only customer authentication for Telegram Mini Apps: strict raw init-data verification, internal User/TelegramAccount linking, customer sessions, refresh rotation with reuse detection, CSRF-protected cookie refresh flows, profile/session APIs, rate limiting, audit/security events, deterministic tests, and documentation.

## Non-goals
No Telegram bot `/start`, bot menus, customer dashboard, store, products, wallet, payments, panel integrations, provisioning, subscriptions, referrals, tickets, reseller behavior, or complete frontend UI are included.

## Threat assumptions
Attackers may forge init data, replay stale Mini App launches, steal refresh cookies, attempt CSRF, reuse consumed refresh tokens, enumerate account status, abuse session-management APIs, scrape logs, or trigger Redis outages. Raw init data, bot tokens, signatures, access/refresh credentials, CSRF values, token hashes, and full Telegram payloads are never logged or returned.

## API decisions
Versioned customer routes live under `/api/v1/customer/auth/...`. Routes are thin FastAPI adapters over customer authentication services. Access credentials use customer-only issuer/audience values and cannot authorize admin routes; admin credentials cannot authorize customer routes. Refresh credentials use separate customer cookie names and paths.

## Acceptance criteria
- Raw Telegram Mini App init data is verified server-side with duplicate, malformed, expired, future, oversized, and modified data rejected.
- Customer identity linking creates or updates safe Telegram fields transactionally and activates first verified PENDING customers.
- Customer sessions rotate refresh generations, store only hashes, revoke immediately, and revoke families on reuse.
- Cookie-authenticated state changes require customer CSRF state.
- Customer profile and session APIs enforce ownership and status.
- Documentation and tests cover the implemented backend without adding commerce or UI behavior.

## Mermaid flows

```mermaid
sequenceDiagram
  participant T as Telegram Mini App
  participant API
  participant DB
  T->>API: raw init data
  API->>API: verify hash/auth_date/user
  API->>DB: create User + CustomerProfile + TelegramAccount
  API->>DB: create customer session
  API-->>T: access token + HttpOnly refresh cookie + CSRF
```

```mermaid
sequenceDiagram
  participant T as Returning Customer
  participant API
  participant DB
  T->>API: raw init data
  API->>DB: find TelegramAccount by Telegram ID
  API->>DB: update safe Telegram profile fields
  API->>DB: create customer session
  API-->>T: access token + rotated customer cookie state
```

```mermaid
sequenceDiagram
  participant C as Customer
  participant API
  participant DB
  C->>API: refresh cookie + CSRF
  API->>DB: find active generation
  API->>DB: consume old generation and create next
  API-->>C: new access token + refresh cookie + CSRF
```

```mermaid
sequenceDiagram
  participant X as Attacker
  participant API
  participant DB
  X->>API: consumed refresh cookie
  API->>DB: detect consumed generation
  API->>DB: revoke session family and record events
  API-->>X: generic authentication failure
```

```mermaid
sequenceDiagram
  participant C as Customer
  participant API
  participant DB
  C->>API: logout + access token + CSRF
  API->>DB: revoke current session
  API-->>C: delete refresh cookie
```
