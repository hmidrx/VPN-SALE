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

### Lifecycle and usage
- Expiry-soon Telegram notifications with customer preference controls and anti-spam rollout handling.
- Read-only authoritative Sanaei usage synchronization into existing service-usage projections.
- Fresh/high-enough-confidence remaining traffic exposed to Telegram; stale or ambiguous data remains unknown.
- Telegram warning, critical and confirmed-exhaustion traffic notifications with latest-state revalidation and deterministic outbox deduplication.

### Support and security
- Native support tickets and threaded replies.
- Ticket pagination, customer/agent image attachments, canned responses/macros, SLA escalation and CSAT.
- Account security and customer session revocation.

## Next — ordered priorities

### 1. BOT-SVC-CONCURRENCY — harden service-operation admission around unresolved provider outcomes
**Why:** renewal/add-traffic execution is real and retry-safe, but a later paid mutation must never compound an earlier unresolved provider state for the same service.

Before coding, inspect current admission and execution serialization. Specifically verify behavior when the previous operation is in states such as `UNCERTAIN`, `PARTIALLY_APPLIED`, `COMPENSATION_REQUIRED` or `MANUAL_REVIEW`.

Target outcome:
- define a minimal safe per-service admission policy for unresolved provider mutations;
- prevent unsafe second paid mutations while preserving legitimate recovery/compensation paths;
- keep quote/payment handling server-authoritative and avoid charging for an operation that cannot safely be admitted;
- provide a safe customer-facing Telegram explanation/action when temporarily blocked;
- add concurrency/idempotency/recovery tests and preserve existing successful parallelism where it is actually safe.

Do not implement a blanket "block every non-success state" rule without proving it is correct.

### 2. BOT-RECOVERY-UX — customer-safe recovery guidance for exceptional operation states
After concurrency policy is explicit, improve Telegram handling for cases that require reconciliation/manual review/compensation so the customer knows whether to wait, retry, contact support or avoid another payment. Never expose provider/reconciliation internals.

### 3. BOT-OPERATOR — Telegram-native operator/admin actions, only where they remove a real operational dependency
Customer standalone Telegram is the current priority. A full admin bot is **not** required to call customer v1 complete, but selected operator flows may be valuable later if the product goal becomes "no Admin Web dependency at all." Reuse existing backend authorization/audit/approval rules; do not create a second admin authority model in Telegram.

### 4. PROD-READINESS — provider-enabled staging and real end-to-end smoke
Do this when the user decides functional bot work is sufficiently complete.

Minimum staging sequence:
- Telegram purchase -> authoritative quote/payment -> worker -> Sanaei provisioning -> activation -> secure subscription/config delivery;
- renewal and add-traffic against a disposable service;
- authoritative usage sync and lifecycle/traffic notifications;
- restart/retry/idempotency checks around worker/provider boundaries;
- verify provider-write gate is enabled only in the intended staging environment with valid operator configuration.

Do not turn the normal restrictive CI/test environment into a provider-writing environment.

### 5. OPS-HARDENING — monitoring, recovery and runbooks
- bounded alerts for failed/retrying/reconciliation work;
- queue/outbox lag visibility;
- provider-read/write health and stale-usage visibility without leaking credentials;
- backup/restore and migration rollback rehearsal;
- concise operator recovery runbooks for states that automation intentionally cannot resolve.

### 6. MULTI-PROVIDER — only after Sanaei flow is stable in staging/production
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
