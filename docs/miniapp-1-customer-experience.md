# MINIAPP-1 customer experience

## Audit and navigation

The customer application already exposes home, catalog and quote builders, checkout,
orders, invoices, payments, services and delivery, wallet and manual card-transfer,
support, profile, security, and session routes. Authentication uses the existing
cookie-backed browser bootstrap or validated Telegram `initData`; the raw credential
is exchanged in the request body and is not persisted in browser storage.

The previous shell placed the store in the five-item navigation while support was
hidden in account settings. The primary destinations are now **home, services,
wallet, support, and account**. Purchase remains available from the home action and
catalog routes remain directly addressable. Detail routes remain direct-linkable and
Telegram's back button delegates to browser history, with home as the safe fallback.

## Design and behavior

Customer-only primitives provide a compact page header, premium card, status badge,
empty/error state, inline notice, section header, and list row. The shell is RTL-first,
uses logical properties, reserves Telegram safe areas and bottom-navigation space,
keeps controls at least 44px, hides bottom navigation for short keyboard viewports,
and disables nonessential motion when requested. Support and account use these
patterns; account intentionally omits database, Telegram, wallet, journal, and
session identifiers.

The Telegram bridge remains the sole Mini App authentication path. It expands before
login, calls `ready` after initialization, synchronizes theme and viewport CSS, and
registers and cleans up the native back button. Browser fallback, loading, expired,
invalid, rate-limited, unavailable, and retryable network states retain the existing
state machine. No sensitive response is persisted or added to URLs.

Home actions and existing surfaces use authoritative customer APIs only. Missing
service and wallet information is represented as an invitation or navigation action,
not synthetic balances, usage, locations, charts, or success states. Manual top-up
request creation, direct/support-only destination handling, receipt upload and
cleanup, ownership protections, CSRF, idempotency, history, and detail behavior are
unchanged.

## Operations, rollback, and deferred scope

The change is frontend-only and adds no dependency, API contract, migration, or
runtime setting. Roll back the single MINIAPP-1 commit to restore the prior shell.
Local startup remains `npm ci && npm run build` followed by the documented Docker
Compose flow.

Explicitly deferred: admin and reseller redesigns, public username/password
registration, a durable support-conversation backend, native Telegram bot receipt
intake, new provider integrations, and automatic bank verification.
