# Phase 1A.1.2 — real product UI and honest visual QA

## Confirmed baseline

At base commit `c4f76856`, the visual suite gave sign-in, registration, recovery, and admin TOTP different filenames while every case loaded `/ui-preview`. The named surface was neither navigated to nor asserted. Dashboard captures also changed only a role badge, so customer, reseller, and admin evidence was misleadingly similar.

This phase keeps visual QA but assigns every composition a deterministic, gated route and verifies its unique Persian heading, semantics, direction, theme, focus, overflow, network inactivity, and screenshot identity.

## Product boundaries

Preview forms are presentation-only and prevent submission. They do not authenticate, persist Telegram `initData`, issue tokens, or write commerce data. Preview routes return not-found in production unless `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true` was present at build time.

Reseller remains a compatibility surface. A reseller is a role on a customer identity at `app.dr-ping.com`: ordinary customer navigation remains available and reseller capabilities are additive. The existing reseller application is not redirected or removed; a future redirect depends on authoritative unified role-based login.

## Visual artifacts and rollback

`npm run test:e2e` creates individual PNGs, `test-results/screenshots/manifest.json`, `test-results/screenshots/contact-sheet.png`, and the Playwright HTML report. CI should upload these together as `phase-1a1-real-product-ui`. Rollback is code-only: revert this commit; there are no migrations, provider changes, or operational data changes.

Local preview: `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true npm run build -w @vpnsale/customer-web` then start the workspace and open `/ui-preview/customer` or a focused `/ui-preview/auth/*` route.
