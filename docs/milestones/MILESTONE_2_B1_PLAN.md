# Milestone 2-B1 — Administrator catalog interface

## Scope and page inventory
Milestone 2-B1 adds the administrator-only catalog console under `apps/admin-web/app/catalog`. Routes cover overview, categories, category create/edit/archive, product list/create/detail, version history, draft version editing, fixed and customizable plan editors, option and typed constraint editors, price-list detail, pricing-rule and tier editors, fulfillment requirements, administrative preview, publication review, validation-error, unauthorized, service-unavailable, and generic safe error states.

## API coverage
The UI is wired around the real Milestone 2-A administrator catalog surface: `/api/v1/admin/catalog/categories`, `/products`, `/products/{id}/versions`, `/publish`, `/pause`, `/price-lists`, `/price-list-versions/{id}/rules`, and `/preview`. The typed client preserves in-memory access tokens, refresh single-flight, CSRF headers, correlation IDs, cursor-page shape, structured validation/conflict errors, abortable lists, and no automatic retry for non-idempotent mutations.

## Product-version editing policy
Published versions are read-only. Editing published content creates a new draft through the backend version endpoint. Draft and published states are visually distinct; publication is only shown after server confirmation. Stale updates, duplicate priorities, overlap, and concurrent publication conflicts are mapped to safe reload/reconcile messaging.

## Pricing editor UX
Money is canonical integer rial with explicit derived toman display. Traffic uses deterministic GB/TB to bytes conversion. Duration is fixed days and never labelled as a calendar month. Pricing rules are structured by backend rule type only; no formulas or executable text are accepted. Tier editors distinguish graduated and bracket/volume behavior and validate overlap/inverted ranges.

## Publication workflow
Administrators validate, preview with the server pricing engine, review identity/content/options/constraints/pricing/fulfillment/channel availability, then explicitly confirm publication. Validation errors are grouped by product content, plan options, constraints, pricing, fulfillment requirements, localization, and availability. The UI never bypasses backend validation.

## Permission policy
Navigation and controls are permission-aware for `catalog.read`, `catalog.create`, `catalog.update`, `catalog.publish`, `pricing.read`, `pricing.manage`, and `quotes.read`. Hidden navigation is usability only; backend authorization remains authoritative. Permission changes apply after profile refresh, and authorization data is not persisted in browser storage.

## Accessibility and localization
The console is Persian-first RTL with English string preparation, LTR machine codes, keyboard-friendly move controls, labelled fields, error summaries, safe states, non-color-only statuses, focus indicators, reduced-motion support, responsive tables/cards, and accessible confirmation areas.

## Non-goals
This milestone does not implement customer storefront, custom-plan builder, checkout, wallet, ledger, orders, invoices, payments, provider instances, servers, nodes, inbounds, allocation, provisioning, subscription links, QR codes, coupons, referrals, tickets, broadcasts, resellers, or financial analytics.

## Acceptance criteria
Acceptance requires real API-backed category/product/price/preview/publication workflows, immutable published versions, safe fixed/custom plan editing, provider-neutral options and fulfillment requirements, typed constraints, explicit rial/toman and byte/day UX, permission-aware routes, behavioral tests, deterministic E2E coverage plan, green verification, no secrets, and documentation matching implementation.
