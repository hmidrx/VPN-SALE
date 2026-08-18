# VPN-SALE Roadmap

Last reviewed: 2026-08-18

## Source of truth
This roadmap is the concise current plan for the repository. For implementation decisions, use this order of trust:

1. current `main` code, migrations and tests;
2. root `AGENTS.md` safety/agent contract;
3. this roadmap;
4. dedicated current feature/ADR documentation;
5. historical milestone plans, old PR text and old README milestone scope notes.

If a historical document says a capability is out of scope but current `main` already implements it, **do not remove or rebuild the capability**. Verify the current implementation and continue from it.

## Current phase
**Telegram customer bot functional completion and hardening before production deployment.**

The customer should be able to complete the normal service lifecycle inside Telegram without depending on the customer website or Mini App. Backend/API/worker work is part of this phase when Telegram correctness requires it. New website/app product work is deferred unless the product priority is explicitly changed.

## Done on current main
The following are existing capabilities and should be treated as foundations, not future roadmap items.

### Telegram customer foundation
- Telegram identity linking and customer-safe private API projections.
- Redis-backed bounded conversation state.
- Persian-native Telegram navigation and compact/versioned callbacks.
- Profile, wallet, service list/details, support and account/security flows.
- Notification preferences use the authenticated private Telegram bridge; caller-supplied raw Telegram IDs are not exposed as a public preference authority.

### Purchase and wallet
- Native Telegram purchase wizard.
- Server-authoritative configurable plans and price quotes.
- Wallet-funded checkout with idempotent accounting boundaries.
- Manual card-to-card wallet top-up with receipt, status and cancellation flow.

### Provisioning and delivery
- Real Sanaei/3x-ui provisioning path with explicit provider-write gate.
- Activation/delivery worker semantics.
- Durable subscription tokens and multi-format retrieval.
- Explicit secure subscription/direct-config reveal from Telegram without Mini App dependency.

### Service management
- Renewal eligibility, authoritative quote, wallet payment and provider execution.
- Add-traffic eligibility, authoritative quote, wallet payment and provider execution.
- Telegram status/result UX for paid service operations.
- Proactive terminal service-operation outcome notifications.
- Rich service detail screen with lifecycle, delivery readiness, expiry and refresh.
- Per-service admission/serialization prevents a later paid mutation from compounding in-flight or unresolved provider work.
- Wallet payment revalidates operation admission under the service lock before financial mutation.
- Customer-safe Telegram handling explains blocked/racing operations without exposing provider or reconciliation internals.

### Lifecycle and usage
- Expiry-soon Telegram notifications with customer preference controls and anti-spam rollout handling.
- Read-only authoritative Sanaei usage synchronization into existing service-usage projections.
- Fresh/high-enough-confidence remaining traffic exposed to Telegram; stale or ambiguous data remains unknown.
- Telegram warning, critical and confirmed-exhaustion traffic notifications with latest-state revalidation and deterministic outbox deduplication.

### Support and security
- Native support tickets and threaded replies.
- Ticket pagination, customer/agent image attachments, canned responses/macros, SLA escalation and CSAT.
- Account security and customer session revocation.
- Service-operation concurrency, admission and recovery UX hardening from PRs #138-#140 is complete and must not be reimplemented.

### Operational hardening
- Authenticated admin-only Telegram production-path health snapshot.
- Prometheus-compatible low-cardinality metrics for due/retrying/failed outbox work, stale claims, fulfillment attention states, unresolved paid service operations and authoritative usage-sync freshness.
- Fixed `HEALTHY` / `DEGRADED` / `ACTION_REQUIRED` classification without customer IDs, Telegram IDs, provider endpoints, remote identities or credential-bearing labels.
- Durable fixed-role heartbeat for the main Telegram production worker so a dead/stale worker is distinguishable from a healthy empty queue.
- Bounded worker cycle success/failure counters and repeated-cycle failure escalation without hostname/process/instance metric dimensions.
- Recovery guidance for bounded health and worker-liveness signals in `docs/ALERTING.md`; recovery must preserve idempotency, reconciliation and provider-write gates.
- Repeatable non-production recovery drill covering stale durable claims, terminal outbox non-replay, unresolved paid-operation admission, unknown-on-provider-read-failure behavior and heartbeat/restart safety.
- `scripts/verify-recovery-drill.sh` refuses production/provider-write mode and runs the focused recovery contract suite; `docs/RECOVERY_DRILL.md` documents the smallest safe operator actions.

## Next — ordered priorities

### 1. PROD-READINESS — provider-enabled staging and real end-to-end smoke
Repository recovery contracts are now exercised without unsafe automatic mutation. The next milestone is a provider-enabled **staging-only** harness plus a real smoke against a disposable certified Sanaei environment. CI must remain restrictive and must never become a provider-writing environment.

Target outcome:
- add a staging-only preflight/verification path that refuses CI/test/production misuse and requires explicit provider-write opt-in;
- keep all credentials/tokens outside Git and avoid secret-bearing CLI arguments where practical;
- Telegram purchase -> authoritative quote/payment -> worker -> Sanaei provisioning -> activation -> secure subscription/config delivery;
- renewal and add-traffic against a disposable service;
- authoritative usage sync and lifecycle/traffic notifications;
- restart/retry/idempotency checks around worker/provider boundaries;
- verify unresolved service-operation admission remains safe under real provider timing;
- clearly separate repository-harness readiness from the external real-smoke result: do not call the system production-ready until the external staging smoke passes.

### 2. BOT-OPERATOR — Telegram-native operator/admin path
The requested end-state includes removing the routine Admin Web dependency for selected support/recovery operations. Build the smallest safe operator surface and reuse backend admin authorization/audit/approval rules; Telegram must not become a second admin authority model.

Target outcome:
- explicit operator identity/linking backed by existing admin authority; never trust a caller-supplied Telegram ID as admin authority;
- Telegram-native read-only operational health and attention summaries first;
- selected high-value support/recovery actions only when an existing backend permission/audit/approval rule can be reused;
- provider credentials, raw errors and customer connection secrets never enter Telegram;
- no duplicated financial/provider business rules in the bot.

### 3. MULTI-PROVIDER — only after Sanaei is stable in staging/production
Preserve provider-neutral contracts now, but add another real provider only from verified API behavior and dedicated contract tests. Do not infer a panel API or claim compatibility from similarity to 3x-ui.

## Deferred while Telegram-first priority is active
- New customer website/Mini App commerce UX.
- Website redesign/polish unrelated to Telegram correctness.
- New reseller-web product features unrelated to bot requirements.
- Broad admin-web feature expansion unless required by a bot/recovery safety boundary.
- Premature generalization to unsupported panel providers.

Existing web/admin code is not deleted or intentionally broken; repository-wide CI remains required.

## Telegram Bot v1 completion criteria
Customer-facing Telegram v1 can be considered functionally complete when all of the following are true:

- customer can start/link account, view profile and manage sessions;
- customer can choose a plan, receive authoritative pricing, pay from wallet/top up and purchase natively;
- successful paid purchase can provision and activate safely on the certified provider path;
- customer can explicitly retrieve secure connection/subscription material;
- customer can view truthful service lifecycle, expiry and fresh authoritative remaining traffic when available;
- customer can renew and buy extra traffic natively with safe payment/execution/status semantics;
- customer receives terminal operation, expiry and low-traffic/exhaustion notifications with preference/anti-spam controls;
- customer can open and continue support tickets natively;
- unresolved provider-operation states cannot be compounded by a later unsafe paid mutation;
- notification preferences are not authorized from an unauthenticated caller-supplied Telegram ID;
- bounded operational health and explicit main-worker liveness are observable without exposing customer/provider secrets;
- recovery contracts are repeatably verified without replay-all or provider-write shortcuts;
- required repository CI is green;
- before production use, provider-enabled staging/live smoke validates the real end-to-end path and recovery behavior.

## Rules for future AI/Codex continuation
When an AI agent continues this project:

1. Read root `AGENTS.md` and this file first.
2. Fetch current `main`; do not rely on a SHA from an old chat/handoff.
3. Check recent merged/open PRs so work is not duplicated.
4. Inspect the exact implementation and tests before declaring a feature missing.
5. Create a fresh bounded branch/PR from current `main`.
6. Keep current Telegram-first scope unless explicitly changed.
7. Never replace authoritative backend/provider state with Telegram-local guesses.
8. Never add secret-looking fixtures or real config/subscription material to tracked files.
9. Run/follow the full repository verification matrix and fix exact root causes.
10. Merge only with all required checks green and the expected PR head unchanged.
11. After merge, update this roadmap if the completed/next boundary changed.
