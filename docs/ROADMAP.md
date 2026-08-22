# VPN-SALE Roadmap

Last reviewed: 2026-08-22

## Source of truth
Use this order of trust for implementation decisions:

1. current `main` code, migrations and tests;
2. root `AGENTS.md` safety/agent contract;
3. this roadmap;
4. dedicated current feature/ADR/runbook documentation;
5. historical milestone plans and old PR/README scope notes.

Never remove or rebuild a capability merely because an old milestone document called it out of scope. Inspect current `main` first.

## Current phase
**Integrated product refinement and production hardening.** Telegram v1 functionality remains preserved while customer web, Mini App and owner administration move onto one premium visual system. The owner control center must consume authoritative existing health/management APIs and must not invent operational or financial values.

## Done on current main

### Customer Telegram foundation
- Telegram identity linking, customer-safe private API projections and Redis-backed bounded conversation state.
- Persian-native navigation, profile, wallet, services, support, notification preferences and account/session security.
- Notification preferences are not authorized from an unauthenticated caller-supplied Telegram ID.

### Purchase, provisioning and delivery
- Native plan selection, server-authoritative pricing, wallet checkout and manual card-to-card top-up.
- Real certified Sanaei/3x-ui provisioning behind the explicit provider-write gate.
- Activation/delivery semantics, durable subscription tokens and explicit secure subscription/direct-config reveal.

### Service management
- Native renewal and add-traffic eligibility, quote, wallet payment, provider execution and result/status UX.
- Per-service serialization/admission prevents compounding in-flight or unresolved paid mutations.
- Customer-safe blocked/race UX and proactive terminal operation notifications.
- Rich service details with lifecycle, delivery readiness, expiry and authoritative refresh.

### Lifecycle, usage, support and security
- Expiry reminders and authoritative Sanaei usage synchronization.
- Truthful remaining traffic when sufficiently fresh/confident; stale/ambiguous data stays unknown.
- Low-traffic, critical and confirmed-exhaustion Telegram notifications with anti-spam/latest-state revalidation.
- Native support tickets, threaded replies, image attachments, pagination, macros, SLA escalation and CSAT.
- Account security/session revocation and service-operation concurrency/recovery safety.

### Operational hardening and recovery
- Authenticated admin-only operational health snapshot and low-cardinality Prometheus metrics.
- Durable fixed-role main-worker heartbeat distinguishing idle healthy work from missing/stale worker liveness.
- Bounded cycle success/failure counters and `HEALTHY` / `DEGRADED` / `ACTION_REQUIRED` classification without customer/provider/instance secrets.
- Recovery guidance in `docs/ALERTING.md`.
- Repeatable non-production recovery drill proving stale-claim recovery, terminal-event non-replay, unresolved paid-operation blocking, unknown-on-provider-read-failure and restart/heartbeat safety.
- `scripts/verify-recovery-drill.sh` refuses production/provider-write mode.

### Provider staging harness — repository side complete
- Dedicated `docker-compose.staging.yml` keeps PostgreSQL/Redis/private services unexposed while preserving the outbound network required for Telegram and Sanaei.
- Provider-write authority is supplied only to the worker; API fake auth/payment remain forced off and the API does not receive provider-write authority.
- `scripts/vpn-sale-compose-staging` isolates the runtime env from the caller shell.
- `platform_worker.staging_preflight` fails closed unless the environment is staging, Telegram polling is enabled, provider writes are explicit and certified Sanaei target/binding/credential/contract metadata exists.
- `scripts/verify-provider-staging.sh` refuses CI/non-staging/loose runtime files/fake auth/fake payment and checks migrations, private ports, API health, bot polling, safe logs and read-only provider readiness metadata.
- `docs/STAGING_E2E.md` defines the disposable real-provider smoke and stop conditions.

### Telegram operator path
- Native hidden `/ops` operational-health screen and safe refresh action are available inside the production Telegram bot runtime.
- Telegram identity is resolved server-side through the existing `telegram_accounts -> identity_users -> admins` relationship; raw Telegram IDs are never treated as administrator authority by themselves.
- Access requires an active administrator plus the backend `ops.telegram.read` permission; the initial migration grants that permission only to the built-in `super_admin` role.
- The private projection reuses the authoritative operational-health collector and returns only bounded aggregate worker/outbox/fulfillment/service-operation/usage state.
- Provider credentials, raw failures, customer connection material, arbitrary customer Telegram IDs and administrator identity details are not returned to Telegram.
- This first operator slice is deliberately read-only; future mutations remain out of scope unless an existing backend permission/audit/approval rule can be reused unchanged.
- `docs/TELEGRAM_OPERATOR.md` documents authorization, safe output and extension rules.

**Important:** repository staging-harness readiness is not a real E2E result. Production-ready status remains blocked until the external disposable Sanaei staging smoke is actually executed with operator-supplied runtime secrets/configuration.

## Next — ordered priorities

### 1. EXTERNAL-STAGING-SMOKE — final production gate
This cannot be completed by repository CI. It requires an operator-controlled staging runtime, Telegram bot token, provider vault configuration, certified Sanaei panel/credentials and a disposable customer/service.

Required real sequence is documented in `docs/STAGING_E2E.md`: purchase -> payment -> provisioning -> activation -> secure delivery -> usage -> renewal -> add traffic -> notifications -> restart/idempotency -> unresolved-operation admission -> recovery.

Do not mark the bot production-ready until this external smoke passes.

### 2. MULTI-PROVIDER — only after Sanaei is stable
Preserve provider-neutral contracts now, but add another provider only from verified API behavior and dedicated contract tests. Never infer compatibility from similarity to 3x-ui.

## Active integrated-experience work
- Premium shared visual language for the customer web and Mini App, including deliberate light/dark themes and mobile-first Persian typography.
- Owner control center for site, bot, Mini App, provider, support, finance and operational triage using existing authenticated APIs and permissions.
- Repository cleanup only when code is proven unused by references, builds and tests; historical names alone are not proof.

## Deferred
- New reseller-web product features unrelated to the current integrated customer/owner experience.
- Additional Telegram operator mutations without an existing backend authorization/audit/approval contract.
- Premature unsupported-provider generalization.

Existing web/admin code must remain unbroken and repository-wide CI remains required.

## Telegram Bot v1 completion criteria
Customer Telegram v1 is functionally complete when:

- account/profile/session management works natively;
- authoritative purchase/top-up/wallet checkout works natively;
- paid purchase provisions and activates safely on the certified provider path;
- secure connection material is explicitly retrievable;
- service lifecycle/expiry/fresh authoritative traffic is truthful;
- renewal/add-traffic are safe, idempotent and trackable;
- operation/expiry/traffic notifications respect preferences and anti-spam controls;
- support is fully usable natively;
- unresolved provider work cannot be compounded by repeat payment;
- operational health and worker liveness are observable without sensitive identifiers;
- recovery contracts are repeatably verified without replay-all/provider-write shortcuts;
- selected operational triage is available natively to an authorized Telegram administrator without creating a second authority model;
- required repository CI is green;
- **before production use**, the external provider-enabled disposable staging smoke passes.

## Rules for future AI/Codex continuation
1. Read root `AGENTS.md` and this file first.
2. Fetch current `main`; never rely on an old chat SHA.
3. Check recent merged/open PRs before starting work.
4. Inspect exact code/tests before declaring a feature missing.
5. Use a fresh bounded branch/PR from current `main`.
6. Keep Telegram-first scope unless explicitly changed.
7. Never replace authoritative backend/provider state with Telegram-local guesses.
8. Never put real credentials/tokens/subscription material in Git or fixtures.
9. Follow the full repository verification matrix and fix exact root causes only.
10. Merge only when all required checks are green and expected PR head is unchanged.
11. Update this roadmap whenever the Done/Next boundary changes.
