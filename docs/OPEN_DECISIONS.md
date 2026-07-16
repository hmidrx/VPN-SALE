# Open Decisions

Open decisions: legal markets and currencies; exact PasarGuard OpenAPI schema; exact Sanaei 3x-ui installed version/API; payment providers and credentials; SMS/email providers; production hosting region; final charting package; whether admin TOTP is mandatory at launch; reseller credit policy; data retention durations.

Milestone 0 infrastructure decision: commit the generated `package-lock.json` after the first successful Codespaces bootstrap; remove the temporary no-lockfile CI fallback in a follow-up Milestone 0 cleanup once the lockfile is present.

Milestone 1A open decisions: final production identity encryption key storage/KMS, exact admin lockout thresholds, whether admin TOTP is mandatory at launch, audit/security event retention periods, IP/user-agent metadata minimization rules, and the Milestone 1B secure administrator bootstrap UX.

Milestone 1B-A open decisions: final production Redis fail-closed SLO, exact admin TOTP mandatory rollout date, production signing-key storage/KMS, trusted-device policy, and formal browser CSRF header naming for the future admin UI.

Milestone 1B-B open decisions: final KMS integration for admin signing/encryption keys, formal production Redis SLO and alert routing, whether TOTP becomes mandatory for every admin, and whether trusted-device labels should be user-editable beyond the current safe display model.

## Milestone 1C-A customer authentication note
Customer Telegram Mini App authentication now verifies raw init data, links Telegram identities to internal customers, issues isolated customer access credentials, rotates opaque refresh-cookie sessions, enforces CSRF on cookie-authenticated state changes, rate limits sensitive operations, and records sanitized audit/security events. Commerce and customer UI remain out of scope.
## Milestone 1C-B1 open decisions
Choose the production public Telegram bot username, final Mini App visual QA matrix across Telegram clients, and the exact CI-owned signed-init-data fixture for browser E2E. Service-worker caching remains intentionally skipped to avoid authenticated response caching risk.
