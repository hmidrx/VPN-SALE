# Threat Model

Threats: credential theft, panel compromise, Telegram init data forgery, session theft, CSRF, XSS, SSRF, SQL injection, webhook forgery/replay, duplicate payments, wallet races, double provisioning, IDOR, privilege escalation, unsafe uploads, secret/log leakage, malicious panel responses, supply chain risk, backup exposure, and insider abuse. Controls map to docs/SECURITY.md.

## Milestone 1A additions

New controls reduce credential theft, session replay, privilege escalation, and audit-log leakage risks. Raw passwords, refresh tokens, recovery codes, and TOTP secrets are not stored. Unique constraints protect duplicate normalized administrator email, Telegram ID, role-permission pairs, admin-role pairs, and token hashes. Remaining risks include future login endpoint rate limits, admin bootstrap hardening, TOTP enrollment UX, and production key-management decisions.

## Milestone 1B-A administrator authentication threats

New controls address administrator credential stuffing, account enumeration, stolen refresh-token replay, MFA replay, recovery-code reuse, CSRF on cookie-authenticated endpoints, and secret leakage through logs/audit metadata. Remaining risks include selecting production Redis availability posture, final KMS-backed identity encryption key storage, and operational signing-key rotation runbooks.

## Milestone 1B-B updated controls

CSRF attacks against refresh-cookie endpoints are mitigated with session-bound tokens. Cross-administrator session revocation is denied by ownership checks. Redis limiter outage in production-like environments is treated as a sensitive authentication failure rather than unlimited access. The admin frontend avoids localStorage/sessionStorage for access tokens.

## Milestone 1C-A customer authentication note
Customer Telegram Mini App authentication now verifies raw init data, links Telegram identities to internal customers, issues isolated customer access credentials, rotates opaque refresh-cookie sessions, enforces CSRF on cookie-authenticated state changes, rate limits sensitive operations, and records sanitized audit/security events. Commerce and customer UI remain out of scope.
