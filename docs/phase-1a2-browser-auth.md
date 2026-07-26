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
HttpOnly refresh cookie. It accepts only the normalized `public_app_origin` (independent of
the broader global CORS list) and requires `X-VPN-Sale-Client:
customer-web`, and same-origin/same-site Fetch Metadata when supplied. Cross-site and null
origins fail before database dependencies. Success consumes and rotates the refresh session,
sets the existing cookie contract, and returns an access token plus fresh raw CSRF token;
failure is generic and does not set a cookie. Responses are `no-store`.

CORS credentials are allowed only for exact `cors_allowed_origins` (which must contain
`public_app_origin`). Wildcards with credentials fail startup. Methods are GET, POST, DELETE,
PATCH, PUT, and OPTIONS; PUT remains required by the admin wallet-policy browser client.
Request headers are Authorization, Content-Type, X-Request-ID,
X-Correlation-ID, X-CSRF-Token, and X-VPN-Sale-Client. Only Retry-After and X-Request-ID
are exposed. Starlette handles preflight before route dependencies, so OPTIONS opens no DB.
Global CORS determines which first-party customer, admin, and reseller frontends may call
their respective API routes. The browser request guard is a separate, narrower trust boundary:
only the customer app Origin may exchange an ambient customer refresh cookie for customer
tokens. Adding an Origin to global CORS must never grant customer bootstrap permission.
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

## Failure-side transaction persistence hotfix

Request-scoped database sessions commit after a successful endpoint return and roll back when
an exception leaves the endpoint. Customer-auth previously used ordinary `ValueError` for both
read-only rejection and rejection after deliberate security mutations. Consequently refresh
reuse returned 401 while rolling back family revocation, the reuse marker, and its events;
password failures similarly lost counters, lockout timestamps, and events.

Customer auth now has a narrow state-changed failure hierarchy. Only these declared failures
are committed by the customer-auth route boundary before it returns the existing generic error.
Unknown/invalid credentials and validation failures remain rollback-only. Low-level services do
not commit, and the global database dependency is unchanged. A commit error escapes and produces
a server failure, so persistence failure cannot produce authentication success. The declared
cases are refresh reuse, password-attempt state, registration conflict after its nested rollback,
and status-block security events.

Route-level regressions use the production transaction lifecycle and fresh verification sessions.
They cover refresh and browser-bootstrap replay, whole-family revocation without affecting an
independent login, access/refresh rejection after replay, separate-request lockout counters and
reset, registration conflict, invalid validation input, unknown refresh credentials, generic
responses, absent failure cookies, and event metadata that contains no submitted credential.

Rollback is code-only and requires no migration: revert the exception contract and route handling.
That rollback reintroduces the known failure-state loss, so deploy it only while password login and
public registration remain disabled and after invalidating affected refresh families. Both auth
feature flags remain disabled by default; local startup still requires an explicit isolated opt-in.
