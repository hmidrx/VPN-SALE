# ADR 0001: Administrator Token and Session Architecture

## Status
Accepted for Milestone 1B-A.

## Decision
Administrator authentication uses short-lived signed JWT access tokens and opaque random refresh credentials stored in an HttpOnly cookie for browsers. The database remains authoritative for authorization because every access token contains a server-side `admin_sessions.id` that must exist, be unrevoked, unexpired, and owned by an active administrator.

Refresh tokens are never stored raw. They are hashed with the existing opaque-token primitive and rotated on every refresh. A consumed refresh token presented again is treated as probable theft and revokes the session family.

## JWT requirements
JWT validation allows only HS256, validates issuer/audience/expiry, uses bounded clock skew, includes `sub`, `sid`, `iat`, `exp`, `jti`, and carries a `kid` header. Signing-key rotation is performed by introducing a new key ID, accepting the previous key for no longer than the access-token lifetime, then retiring it.

## Consequences
The design allows immediate server-side revocation, avoids storing bearer refresh secrets, and limits access-token blast radius. It requires durable session storage and careful cookie/CSRF handling for browser clients.
