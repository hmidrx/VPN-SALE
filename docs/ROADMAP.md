# VPN-SALE Product Roadmap

Last reviewed: 2026-08-25

## Product outcome

VPN-SALE is one deployable, Persian-first sales and operations platform with four
coherent surfaces:

1. a complete Telegram sales and support bot;
2. a mobile-first Telegram Mini App and customer website backed by the same APIs;
3. an owner/admin control center for catalog, customers, money, providers, support,
   content, security and operations;
4. a durable API/worker layer that safely operates multiple certified Sanaei/3x-ui
   panels and multiple inbounds per sellable plan.

The target provider contract for this release is **Sanaei/3x-ui 3.7.0**. Supporting
that version means a versioned, fixture-backed contract and a real disposable staging
certification; it must never be inferred from an older contract or enabled blindly.

## Source of truth

Use this order of trust for implementation decisions:

1. current `main` code, migrations and tests;
2. root `AGENTS.md` safety/agent contract;
3. this roadmap;
4. dedicated current feature/ADR/runbook documentation;
5. historical milestone plans and old PR/README scope notes.

Never remove or rebuild a capability merely because an old milestone document called
it out of scope. Inspect current code and tests first.

## Release principles

- PostgreSQL remains the durable source of truth. Redis stores bounded ephemeral state.
- Website, Mini App and bot are clients of the same authoritative domain/API behavior;
  they do not fork pricing, wallet, ownership, payment or provisioning rules.
- Money is integer rial and every financial mutation is idempotent, auditable and
  balanced through the ledger.
- Provider credentials and connection material are encrypted or tokenized, never
  logged, and never exposed through customer/admin list projections.
- Provider writes stay fail-closed behind an explicit deployment gate. Readiness in CI
  does not authorize real panel mutation.
- Customer delivery uses revocable opaque public tokens. A custom subscription origin
  changes presentation, not the underlying security boundary.
- A feature is complete only with API authorization, persistence, worker behavior,
  customer-safe UX, admin controls, audit events, observability, tests and recovery
  behavior where applicable.
- “Release-ready” means no known severity-1 or severity-2 defect, all required checks
  green, migrations and rollback validated, and the external staging acceptance run
  completed. It is not a promise that software can never contain a defect.

## Verified on current main

### Telegram and customer foundation

- Telegram identity/linking, Persian navigation, Redis-backed bounded conversation
  state, customer-safe private projections and account/session security.
- Native plan selection, server-authoritative quotes, wallet checkout, manual
  card-to-card top-up and receipt review.
- Service list/details, secure subscription/direct-config reveal, renewal, add traffic,
  operation status, expiry reminders, traffic notifications and native support/CSAT.
- Notification preferences are authorized through customer/session or private
  service-authenticated surfaces, never a caller-supplied Telegram ID.

### Commerce and provisioning foundation

- Catalog, pricing, order/invoice, wallet/ledger and manual top-up domain foundations.
- Durable fulfillment/activation work with idempotency and provider-write safety gates.
- A certified Sanaei/3x-ui adapter contract currently exists for an older pinned
  version and must be upgraded/certified for the 3.7.0 target below.
- Usage synchronization treats stale, ambiguous or low-confidence provider data as
  unknown instead of fabricating a healthy zero.

### Operations foundation

- Authenticated admin operational health, Prometheus metrics and fixed-role worker
  heartbeat.
- Recovery drill, staging harness, provider preflight, runbooks, backups and deployment
  documentation.
- Read-only Telegram `/ops` path for authorized operators using backend RBAC.

### Integrated product foundation

- Customer web/Mini App, admin web and shared UI packages exist and are covered by
  frontend checks.
- Several admin surfaces already consume real APIs, while some older management pages
  still contain static or preview-only rows/actions and are not considered complete.

## Execution plan — ordered and release-gated

### 0. BASELINE — roadmap, inventory and defect closure

- Record the requested end state and acceptance gates in this file before product code
  changes.
- Run the full backend, frontend, security, Compose and deterministic UI verification
  matrix on an exact current-main checkout.
- Inventory every route, API, migration, worker job, bot flow and admin action as real,
  preview-only, incomplete or dead. Remove only code proven unused.
- Fix every reproducible failure and create a regression test before expanding scope.
- Produce a traceable feature matrix linking each user/admin flow to its API permission,
  test and operational owner.

**Exit gate:** clean baseline; no ignored failing checks; no known severity-1/2 issue;
roadmap and feature matrix match the repository.

### 1. PROVIDER-370 — multi-panel Sanaei/3x-ui 3.7.0 certification

- Add a versioned `v3.7.0` provider contract from verified upstream behavior, sanitized
  HTTP fixtures and explicit capability flags.
- Support multiple active panels with encrypted credentials, per-panel base path,
  TLS policy, timeouts, health state, maintenance/drain mode, capacity and priority.
- Implement authenticated session renewal, bounded retry/backoff, response validation,
  clock-safe expiry handling and circuit breaking without leaking cookies or raw errors.
- Provide admin create/edit/test/disable/drain/rotate-credential flows protected by RBAC,
  step-up confirmation and audit events. Secret values are write-only.
- Synchronize inbounds and safe capacity metadata; never delete or rewrite unknown
  remote configuration.
- Certify create, inspect, update, extend, add-traffic, disable, delete/revoke, usage and
  subscription behavior against a disposable 3.7.0 instance.

**Exit gate:** contract tests and simulated failure tests pass; real disposable panel
certification report is signed off; provider writes remain disabled by default.

### 2. ROUTING — plan-to-panel and multi-inbound orchestration

- Introduce provider pools and inbound pools. A catalog plan/version selects one pool;
  a pool contains explicit panel/inbound bindings with weight, priority, capacity,
  protocol/capability constraints, region, health and maintenance state.
- Allow one purchased service to own one or more deterministic attachments when a plan
  explicitly requires multiple inbounds. Store the exact versioned allocation snapshot.
- Add routing strategies: pinned, weighted healthy, least-utilized, ordered failover and
  region-aware. Selection is server-side, deterministic for retries and explainable to
  administrators.
- Validate protocol compatibility, uniqueness, quota/duration semantics and capacity
  before catalog publication. A broken mapping cannot be sold.
- Add safe drain and migration workflows with preview, approval, progress, rollback
  boundary and customer notification. Never silently move a customer's identity.
- Expose admin pool/binding CRUD, sync status, capacity, routing simulation and allocation
  history without exposing provider credentials.

**Exit gate:** concurrent fulfillment cannot double-allocate; unhealthy/drained bindings
are excluded; partial multi-inbound failure converges safely; replay is idempotent.

### 3. DELIVERY — branded subscription, QR and connection center

- Resolve provider-returned links when the certified contract supports them, or render
  links only from validated administrator-defined templates and allowlisted fields.
- Add a configurable trusted public subscription origin, path template, brand name and
  help URLs. Reject open redirects, arbitrary hosts, secret-bearing query parameters and
  unsafe template placeholders.
- Return a stable revocable subscription URL, QR code and copyable direct links through
  website, Mini App and bot. QR content must exactly equal the displayed safe URL.
- Support subscription content negotiation for the approved clients/formats already
  represented by provider capabilities, with bounded caching and immediate revocation.
- Add device-aware connection guidance, one-tap copy/open actions, rotation/revoke and
  delivery access audit without logging the secret material.
- Provide admin delivery preview using synthetic data, custom-domain verification,
  certificate/readiness state and per-service revocation controls.

**Exit gate:** token ownership, expiry, rotation, revocation, QR parity, custom-domain
host validation and cache invalidation are covered by integration and browser tests.

### 4. COMMERCE — complete payments, wallet and reconciliation

- Keep wallet purchase and manual top-up fully operational; complete real gateway
  adapters only from documented APIs with signature verification and exact amount/unit
  checks.
- Add idempotent checkout creation, callback/webhook inbox, replay protection, pending
  expiry, success/failure/cancel/refund/chargeback state machines and reconciliation.
- Support admin-configurable payment methods, availability schedules, min/max amounts,
  fees/discount ownership, maintenance mode and safe public instructions.
- Complete wallet history, immutable ledger explorer, manual adjustment with dual
  control, refund/compensation, downloadable safe receipt and finance exports.
- Add coupons/campaigns, referral credit and reseller commission only as separate ledger
  entries with caps, expiry, abuse controls and auditable attribution.
- Add finance dashboards for settlement mismatch, stuck payments, wallet liabilities,
  revenue/refunds and reconciliation age without mutable accounting shortcuts.

**Exit gate:** money conservation and concurrent webhook/payment races are verified in
PostgreSQL; reconciliation identifies and safely resolves every supported mismatch.

### 5. CUSTOMER-EXPERIENCE — complete website and Telegram Mini App

- Use one responsive Persian-first experience for browser and Mini App with deliberate
  light/dark themes, accessible keyboard/touch behavior and correct RTL/LTR isolation.
- Complete sign-in/linking, home dashboard, catalog/search/filter, plan comparison and
  custom-plan builder using server quotes.
- Complete checkout, payment return, wallet/top-up/history and transparent order status.
- Complete service center with usage/expiry, delivery/QR, renew/add-traffic, operation
  progress, notifications, device guides and support.
- Complete profile, security/session management, language/theme/preferences and account
  linking/recovery only when the backend capability is safely enabled.
- Verify Telegram `initData`, theme, viewport, BackButton/MainButton and browser fallback;
  never trust `initDataUnsafe` or persist bearer secrets in browser storage.
- Add honest empty/loading/error/offline/retry states, installable PWA metadata and
  privacy/terms/support surfaces controlled through published configuration.

**Exit gate:** critical customer journeys pass on mobile and desktop, inside Telegram and
in a normal browser, against real APIs with no preview data or inert primary action.

### 6. BOT-V2 — complete sales, service and support bot

- Preserve existing native flows and align catalog, quote, payment, delivery, service and
  support outcomes with the website/Mini App through shared API contracts.
- Add resumable carts, order timeline, payment deep links, QR/document delivery, device
  guide selection, safe broadcast preferences and localized failure recovery.
- Add referral/coupon entry, gift purchase and family/team slots only after corresponding
  authoritative commerce/ownership contracts exist.
- Add operator-approved campaign messages with segment preview, rate limits, opt-out,
  scheduling, dry run and delivery analytics.
- Keep callbacks compact, signed/opaque where sensitive, idempotent and compatible with
  Telegram retries; no price, permission or ownership decision lives in handlers.

**Exit gate:** webhook and polling modes, duplicate/out-of-order updates, rate limits,
restart recovery and all critical native journeys pass without Mini App dependency.

### 7. OWNER-CONTROL-CENTER — replace every preview with real administration

- Complete dashboard and command center for revenue, liabilities, orders, fulfillment,
  active services, expiring capacity, provider health, worker lag, support SLA and alerts.
- Complete RBAC/MFA/session, administrators, customers, audit/security events and safe
  impersonation-free customer assistance.
- Complete catalog/categories/products/versions/pricing, provider pools/inbounds,
  payments/wallet/ledger, orders/invoices/refunds, coupons/referrals/resellers and taxes
  or fees where configured.
- Complete service operations, migration/drain/retry/reconcile, notification templates,
  bot/menu/content settings, support inbox/macros/attachments/CSAT and system branding.
- Every mutation must use a real API, permission, confirmation proportional to impact,
  optimistic concurrency/idempotency, success/error feedback and an audit event.
- Remove all example/static rows, fake tokens, inert submit buttons and “API” placeholders
  from production routes. Demo data belongs only in explicit test fixtures/story routes.
- Add responsive tables/cards, saved bounded filters, cursor pagination, accessible forms
  and CSV exports that exclude secrets and formula-injection payloads.

**Exit gate:** route-to-API/RBAC matrix is complete; no production admin route presents
preview data as fact; destructive and financial/provider actions pass security review.

### 8. INTELLIGENCE — useful automation without hidden authority

- Capacity forecasting, churn/expiry cohorts, anomaly alerts and failed-journey funnels
  use explainable aggregate data and never mutate money or providers automatically.
- Smart plan recommendations remain optional, disclose the factors used and are based on
  real catalog/usage data rather than invented savings.
- Add scheduled maintenance banners, incident status, targeted notifications and
  customer-visible delivery history.
- Add feature flags and staged rollout/kill switches for risky provider, payment and bot
  behavior with audit and metrics.

**Exit gate:** automation can be disabled, its inputs are bounded and observable, and no
customer secret or raw provider identifier enters analytics events.

### 9. PRODUCTION — deployment, recovery and final acceptance

- Provide a hardened single-server reference deployment with TLS reverse proxy,
  PostgreSQL, Redis, private object storage/media, API, worker, bot, customer web and
  admin web; only public web ingress is exposed.
- Validate environment configuration before start, generate no credentials in Git, use
  least-privilege runtime secrets and document rotation.
- Add health/readiness/startup checks, structured redacted logs, metrics/alerts, resource
  limits, database pooling, migrations, daily encrypted backups and restore drills.
- Add zero/low-downtime upgrade, rollback and disaster-recovery runbooks with tested
  database compatibility boundaries.
- Run dependency, secret, static, unit, integration, migration, Compose, deterministic UI,
  browser E2E and load/concurrency checks.
- Execute the external provider-enabled staging journey:
  purchase -> payment -> allocation -> provisioning -> activation -> subscription/QR ->
  usage -> renewal -> add traffic -> migration/drain -> notification -> restart/replay ->
  reconciliation -> revoke.

**Exit gate:** all required CI checks pass on the immutable release SHA; backup restore and
rollback are proven; the external 3.7.0/payment/Telegram smoke report contains no open
severity-1/2 issue; production writes are enabled only by the operator during deployment.

## Cross-surface acceptance matrix

| Capability | Website | Mini App | Bot | Owner admin | Worker/API |
| --- | --- | --- | --- | --- | --- |
| Catalog and authoritative quote | required | required | required | configure/publish | authoritative |
| Wallet, payment and invoice status | required | required | required | operate/reconcile | authoritative |
| Purchase and fulfillment timeline | required | required | required | triage/retry | durable execution |
| Service usage and lifecycle | required | required | required | inspect/operate | sync/authoritative policy |
| Subscription, QR and direct links | required | required | required | configure/revoke | secure resolution |
| Renewal/add traffic/migration | required | required | required | approve/triage | serialized execution |
| Support and notifications | required | required | required | inbox/configure | durable delivery |
| Provider pools and inbounds | hidden | hidden | hidden | full controls | routing/certification |
| Audit, health and recovery | customer-safe only | customer-safe only | operator projection | full bounded view | metrics/runbooks |

## Explicit external decisions and inputs

Implementation may use safe defaults, but production activation requires operator-owned
values that must never be committed:

- domains and DNS for customer, admin, API, bot webhook and subscription origin;
- Telegram bot token/username and webhook or polling choice;
- disposable and production Sanaei/3x-ui panel URLs, credentials, TLS expectations and
  allowed inbound IDs;
- payment provider account, callback domains, credentials and settlement rules;
- card-to-card destination details, business identity/support/privacy text;
- SMTP/SMS/object-storage credentials if those optional channels are enabled.

Missing production secrets never block repository implementation or CI; their dependent
features remain fail-closed and are verified with fake/sanitized contracts until the
operator supplies them out of band.

## Deferred until a verified contract exists

- Any provider family other than the certified Sanaei/3x-ui target.
- Direct writes to a panel database or undocumented provider endpoints.
- Cryptocurrency custody, automatic exchange, credit/negative wallet balances or
  accounting behavior without explicit legal/product requirements.
- Telegram operator mutations that bypass existing backend permission, audit and approval
  rules.

## Continuation rules for AI/Codex agents

1. Read root `AGENTS.md` and this file first.
2. Fetch exact current `main` and inspect recent merged/open work.
3. Start a fresh bounded branch; do not reuse an already-merged branch.
4. Inspect code, migrations and tests before calling a feature missing.
5. Implement vertical slices rather than visual shells or duplicate business logic.
6. Add focused regression, authorization, idempotency and failure/retry tests.
7. Run the complete repository verification matrix and fix root causes only.
8. Never commit a real credential, panel URL, subscription/config, receipt or customer
   identifier.
9. Update this roadmap when a release gate changes state.
10. Merge only with green required checks and an expected-head-SHA guard; record the
    actual merge SHA in the handoff.

