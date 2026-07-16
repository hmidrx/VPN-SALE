# Milestone 1B-B Plan: Administrator Authentication Interface

## Scope
Milestone 1B-B completes and hardens administrator authentication APIs and adds the backend-connected administrator authentication/security frontend. Work is limited to administrator login, MFA, sessions, password change, recovery codes, CSRF/cookie handling, rate limiting, typed schemas, and the security settings UI.

## Non-goals
No customer authentication, Telegram authentication, administrator CRUD, RBAC management, products, wallets, orders, payments, panels, provisioning, reseller commerce, analytics, marketing, or business dashboard behavior is included.

## API gaps addressed
- Replaced per-request SQLAlchemy engine creation with cached engine/session factory dependencies.
- Added typed responses and structured generic API errors with correlation IDs.
- Enforced CSRF on refresh-cookie state-changing endpoints.
- Added current profile, session listing, selected/all/other session revocation, password change, recovery-code regeneration, MFA disablement, and CSRF state endpoint.
- Encapsulated rate limiting behind Redis and deterministic in-memory implementations.

## Security risks and controls
Refresh tokens remain HttpOnly cookies and are never exposed to normal browser JavaScript. Access tokens are memory-only in the admin client. CSRF tokens are session-bound hashes returned after completed authentication and required for cookie-authenticated state changes. Redis limiter failures fail closed for sensitive operations in production-like environments. Password change and MFA disablement require strong confirmation and revoke other sessions.

## Frontend architecture
The admin web app uses Persian RTL defaults, shared design tokens, client-side authentication modules, memory-only access-token storage, refresh single-flight control, CSRF handling, typed API methods, and focused authentication/security pages. Pages are intentionally limited to authentication and security workflows.

## Acceptance criteria
- Admin authentication APIs are typed, ownership-aware, and CSRF protected.
- Database session lifecycle is cached, rollback-safe, and test-overridable.
- Password change, MFA disablement, recovery-code regeneration, session revocation, and current profile are implemented.
- Admin frontend has login, MFA, enrollment, recovery display, profile, sessions, password, MFA settings, and safe state pages.
- Tests cover backend security flows and frontend token-storage policy.
