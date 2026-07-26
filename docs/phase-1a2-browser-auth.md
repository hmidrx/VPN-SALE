# Phase 1A.2.2B — browser authentication bootstrap

## Confirmed pre-change limitation and root cause

The customer shell previously called only Telegram bootstrap. A normal browser therefore
ended in `TELEGRAM_UNAVAILABLE`; the approved sign-in and registration forms were visual
previews whose submit handler intentionally prevented writes. Access and CSRF tokens were
memory-only. Although the HttpOnly refresh cookie survived reload, `/refresh` required the
lost `X-CSRF-Token`, while `/csrf` required the lost access token. That circular contract
made hard-reload restoration impossible. The profile also used `username` solely for
Telegram presentation and had no separate central account username.

Browser credentials and tokens must not be moved into localStorage, sessionStorage, URLs,
Telegram storage, logs, or telemetry to bypass that problem.

## Security contract

New sessions generate an independent 32-byte-or-greater random CSRF value, return the raw
value once, and persist only the salted opaque-token hash. Validation hashes the presented
raw value and uses constant-time comparison. Rotation consumes the old session and rotates
both refresh and CSRF values. A narrow compatibility branch accepts the exact deterministic
legacy representation using constant-time comparison; the next refresh/bootstrap writes a
new-format session. Remove this branch only after the maximum absolute lifetime of all
pre-fix sessions has elapsed. No migration is needed: `csrf_token_hash` retains its purpose.

`POST /api/v1/customer/auth/browser-bootstrap` accepts no payload and uses the scoped
HttpOnly refresh cookie. It requires an exact configured Origin, `X-VPN-Sale-Client:
customer-web`, and same-origin/same-site Fetch Metadata when supplied. Cross-site and null
origins fail before database dependencies. Success consumes and rotates the refresh session,
sets the existing cookie contract, and returns an access token plus fresh raw CSRF token;
failure is generic and does not set a cookie. Responses are `no-store`.

CORS credentials are allowed only for exact `cors_allowed_origins` (which must contain
`public_app_origin`). Wildcards with credentials fail startup. Methods are GET, POST, DELETE,
and OPTIONS. Request headers are Authorization, Content-Type, X-Request-ID,
X-Correlation-ID, X-CSRF-Token, and X-VPN-Sale-Client. Only Retry-After and X-Request-ID
are exposed. Starlette handles preflight before route dependencies, so OPTIONS opens no DB.
For production use `https://app.dr-ping.com` as the public/allowed app origin and
`https://api.dr-ping.com` as API origin; the refresh-cookie domain and auth-only path remain
unchanged.

## Capabilities and UI state machine

`GET /api/v1/customer/auth/capabilities` has settings as its only dependency, exposes six
safe booleans, and is always present. Password login and public registration reflect the
same backend flags that control route inclusion; both remain false by default. A runtime
product-rollout registration flag may further hide registration, but can never override a
false backend security capability.

Startup loads capabilities, attempts browser bootstrap once, and loads profile and sessions
on success. Only a 401 proceeds to Telegram detection and verified init-data login. A normal
browser gets real website actions when enabled and a clean unavailable state otherwise.
Real `/auth/sign-in` and `/auth/register` routes re-check an existing session before showing
forms. Tokens stay in module memory, password confirmation never crosses the network, and
blank optional email is omitted. Both channels converge on the one customer shell.

The profile adds nullable `account_username`; existing `username` retains Telegram meaning.
Password-only accounts therefore expose their presentation username without inventing
Telegram metadata, while Telegram-only accounts return `account_username: null`.

## Rollback and local startup

Rollback is code-only: revert this change; there is no migration. Existing new-format
sessions will no longer validate under pre-change CSRF logic and users must sign in again.
For local development configure exact local origins and explicitly opt in to password login
or registration only for an isolated test run. Repository and deployment defaults remain
disabled. Start with the existing Docker Compose workflow after validating configuration.
