# Phase 1A.2.2A password authentication backend

Public registration creates the active identity, customer profile, Argon2id credential,
optional unverified email, built-in customer role, initial session, and sanitized events in one
transaction. Database uniqueness remains the final authority for normalized username and email;
the service contains uniqueness failures in a savepoint and returns one generic conflict.

Password login locks the credential row, verifies either the stored hash or a valid dummy Argon2id
hash, applies the status and timed-lock checks, updates failure state, and issues a session only on
success. Errors do not distinguish missing identities, credentials, status, lock, or bad passwords.

Telegram and password authentication share the customer session issuer. Token claims, refresh
hashing and families, idle and absolute expiry, CSRF, rotation, reuse detection, and cookie policy
remain unchanged. A five-device maximum is explicitly deferred to the session-policy phase because
rotation families cannot safely be limited with a naive session-row count.

Both endpoints are disabled by default. Production-like rate limits use Redis and fail closed;
keys are salted hashes of IP or normalized username values. No email verification, recovery,
Telegram linking, frontend integration, payments, or provider writes are activated.

Rollback is application-only: disable both flags (the default) and revert the code. No schema
migration is introduced. Local startup continues to use Docker Compose; opt in only in a controlled
environment with `VPN_SALE_PUBLIC_ACCOUNT_REGISTRATION_ENABLED=true` and/or
`VPN_SALE_PASSWORD_ACCOUNT_LOGIN_ENABLED=true`.
