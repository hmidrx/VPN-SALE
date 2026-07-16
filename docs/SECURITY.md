# Security

Security baseline includes Argon2id for future admin passwords, secure cookies, CSRF where applicable, strict CORS/CSP, rate limiting, replay prevention, webhook verification, object authorization, encrypted panel credentials, secret redaction, dependency scanning, secret scanning, backup encryption, and restore testing.

## Frontend dependency audit policy

Milestone 0 CI runs `npm audit --audit-level=high` after `npm ci`/install setup. Critical and high npm advisories fail CI. Moderate advisories are reviewed and documented; they may remain non-blocking only when the available npm fix is incompatible with the supported dependency line or would require a breaking downgrade/major migration that does not reduce risk.

## July 2026 frontend dependency review

The previous frontend baseline used `next@15.1.3`, `react@19.0.0`, `react-dom@19.0.0`, `@types/react@19.0.2`, `@types/react-dom@19.0.2`, and `@types/node@22.10.2` in each web app. That Next.js release was affected by multiple Next.js advisories, including critical React Server Components remote-code-execution exposure in the Next.js App Router line and additional high-severity middleware/proxy and denial-of-service advisories reported by `npm audit`.

The remediated Milestone 0 baseline pins each web app to `next@15.5.20`, `react@19.2.7`, `react-dom@19.2.7`, `@types/react@19.0.2`, `@types/react-dom@19.0.2`, and `@types/node@22.20.1`. This keeps the project on the patched Next.js 15 line instead of taking an unnecessary major-version migration. The React runtime packages were upgraded to patched 19.2.x releases; React type packages remain on the compatible 19.0.x line because Next.js 15.5 generated validation types reference the global `React.ComponentType` namespace shape. Each web app includes a small `react-global.d.ts` compatibility shim for that generated validator while retaining strict TypeScript checks.

Final `npm audit` status after the upgrade: no critical or high vulnerabilities. Two moderate findings remain because `next@15.5.20` pins `postcss@8.4.31`, which is affected by GHSA-qx2v-qp2m-jg93. npm reports the available automated fix as a breaking downgrade to `next@9.3.3`; a root override to `postcss@8.5.10` clears the advisory but makes npm report Next's exact dependency as invalid. Milestone 0 does not use user-supplied CSS stringification or expose products, users, authentication, payments, panels, or other business features. The finding remains documented and non-blocking until Next publishes a compatible patched dependency graph or the project intentionally migrates to a supported release that removes the exact vulnerable PostCSS pin.

## Milestone 1A identity security primitives

Identity secrets use reviewed primitives: Argon2id for administrator passwords, cryptographically random opaque tokens with SHA-256 hashes for persistence, and Fernet authenticated encryption for future TOTP secrets. Encrypted secret records carry a key version so rotation can decrypt old versions while writing new versions. Audit and security metadata rejects secret-looking keys such as passwords, tokens, hashes, credentials, TOTP, recovery codes, and raw Telegram init data.

## Milestone 1B-A administrator controls

Administrator passwords are policy checked before Argon2id hashing. Signed access tokens are short lived; refresh credentials are opaque, cookie-scoped, HttpOnly, and persisted only as hashes. CSRF state is derived per session. TOTP secrets use the existing key-versioned encrypted-secret abstraction, and recovery codes are one-time hashed values. Authentication audit/security metadata is sanitized and rejects secret-looking fields.

Redis-backed distributed rate limiting is the production target; the Milestone 1B-A abstraction includes deterministic in-process tests and documents fail-closed expectations for production Redis outages.

## Milestone 1B-B hardening

The API now uses a reusable SQLAlchemy engine/session factory, structured generic errors, session-bound CSRF checks for refresh-cookie operations, production Redis rate-limiter abstraction with fail-closed behavior, and consistent refresh-cookie creation/deletion attributes. Password change, recovery-code regeneration, and MFA disablement require strong confirmation and avoid logging secrets.

## Milestone 1C-A customer controls
Telegram init data is verified with HMAC-SHA256 according to the Mini Apps data-check-string design and constant-time signature comparison. Customer sessions use distinct issuer/audience/cookie/CSRF configuration from administrator sessions. Customer refresh cookies are HttpOnly, path-scoped to `/api/v1/customer/auth`, Secure in production, and never returned in URLs or browser storage. Rate-limit keys are HMAC-hardened and Redis outages fail closed in production-like environments.
## Milestone 1C-B1 frontend token policy
Customer access tokens, CSRF values, and session identifiers are held in JavaScript memory only and are cleared on logout, revoke-all, and refresh failure. The frontend never uses `initDataUnsafe`, never persists raw init data or tokens to Web Storage/IndexedDB/cookies, never places secrets in URLs, and exposes only public placeholders such as API base URL and bot username.
