# AGENTS.md

## Read this first
This file is the continuation contract for coding agents such as Codex. Read it before changing the repository, then read `docs/ROADMAP.md` and inspect current `main` plus the relevant tests/code. Historical milestone notes can lag behind the implementation; current code, migrations, tests, this file, and the roadmap take precedence over old scope statements.

## Current product priority
The active priority is to finish and harden the **customer-facing Telegram bot as a standalone experience**. Do not start new customer website/app product work unless the user explicitly changes that priority.

Backend/API/worker changes are in scope when they are required to make Telegram functionality correct, safe, durable, or observable. Existing web applications still participate in repository-wide CI; passing their checks does not expand the active product scope.

## Architecture boundaries
- `apps/api`: authoritative business/API layer, persistence models, private Telegram projections, admin/recovery endpoints.
- `apps/telegram-bot`: Telegram-native UX, callbacks, conversation flow and safe rendering. Keep pricing, payment, ownership and provider rules out of handlers.
- `apps/worker`: durable background execution, provider synchronization, notifications, reconciliation and retries.
- PostgreSQL is the durable source of truth; Redis is used for bounded ephemeral/conversation state.
- Provider contracts/adapters live behind provider abstractions. Current real provider work is centered on certified Sanaei/3x-ui behavior; do not imply arbitrary panel compatibility.
- Keep framework-independent business rules in domain/application layers where practical. Do not couple domain code to Telegram, FastAPI, SQLAlchemy or a concrete provider client.

## Non-negotiable safety invariants
- Never commit secrets, production credentials, panel URLs, cookies, private keys, customer configuration material, real subscription links or secret-bearing test fixtures.
- Never read or modify an external panel database directly and never invent undocumented provider endpoints.
- Do not weaken lint, typing, authorization, security scans, migration checks or tests to obtain a green build.
- Money is integer rial; never use floating point for authoritative monetary values.
- Pricing, quote validity, payment state, wallet state, service ownership and operation eligibility are server-authoritative.
- Provider writes remain explicitly gated. Do not casually enable `VPN_SALE_PROVIDER_WRITES_ENABLED`; enabling real mutations is an operator/deployment decision after valid provider configuration and staging verification.
- Financial and provider mutations must be idempotent and retry-safe. Use durable state/outbox patterns, deterministic operation keys/targets and row-level serialization where required.
- Do not expose provider IDs, remote identities, credentials, panel errors, reconciliation snapshots or adapter diagnostics in customer Telegram messages/callback data.
- Do not persist plaintext connection/subscription secrets where the existing secure-delivery/token design intentionally avoids it.
- Revalidate customer ownership at every sensitive read/write boundary; Telegram username is never an identity key.
- Treat stale, ambiguous or low-confidence provider usage as unknown instead of fabricating zero or a false healthy state.

## Completed Telegram capabilities — do not reimplement
Before proposing a milestone, inspect these existing flows. They are already implemented on `main` and should be extended rather than duplicated:
- Telegram identity/linking, customer-safe private projections and Redis conversation state.
- Native purchase wizard with server-authoritative configurable plans, pricing, checkout and wallet payment.
- Manual card-to-card wallet top-up with receipt/status/cancel flow.
- Real Sanaei/3x-ui fulfillment, activation and provider-write safety gates.
- Secure subscription and explicit direct-config delivery without Mini App dependency.
- Service list/details, safe refresh, lifecycle/delivery readiness, expiry and authoritative remaining traffic when available.
- Renewal and add-traffic eligibility, quote, payment, execution, status and terminal-result notifications.
- Service-expiry notifications and authoritative provider usage synchronization.
- Low-traffic, critical-traffic and confirmed-exhaustion Telegram notifications with anti-spam/revalidation.
- Native support tickets, replies, pagination, image attachments, canned responses/macros, SLA escalation and CSAT.
- Customer account security and session revocation.

## Current recommended next engineering priority
See `docs/ROADMAP.md` for ordered work. The first recommended technical hardening item is service-operation concurrency/admission around unresolved provider outcomes. Inspect the current policy before changing it. In particular, determine whether a new paid mutation can be admitted while an earlier mutation for the same service is in an unresolved state such as `UNCERTAIN`, `PARTIALLY_APPLIED`, `COMPENSATION_REQUIRED` or `MANUAL_REVIEW`.

Do **not** solve this by blindly blocking every non-success status. Define the smallest safe policy, preserve recovery paths, add focused tests, and keep the customer-facing reason/action clear.

## Git and PR workflow for agents
1. Fetch the exact current `main` SHA before starting. Never assume the previous conversation's SHA is still current.
2. Create a fresh branch from current `main`; never continue a branch that has already been merged.
3. Keep each change a bounded milestone. Telegram-focused milestones should normally use a `BOT-*` title; documentation-only continuity work may use `DOCS-*`.
4. Add focused tests for changed behavior and failure/retry/idempotency/security boundaries.
5. Open a PR and run the repository's full `Verify Milestone 0` workflow even when only bot/backend/docs files changed.
6. Investigate the exact failing job/log. Fix the root cause; do not relax the check.
7. Merge only when all required jobs are successful and the PR head has not moved. Use an expected-head-SHA guard when merging programmatically.
8. After merge, refetch `main` and record the actual merge SHA in any handoff/status report.

Required CI jobs currently include:
- Backend verification
- Frontend verification
- Security baseline
- Docker Compose verification
- Deterministic visual QA
- Restrictive checkout deployment acceptance

## Toolchain and CI details
- Python target: 3.12.
- Ruff is pinned in repository dev requirements; current verification has used Ruff 0.8.4 formatting/lint semantics.
- Pyright is strict; current verification has used Pyright 1.1.390.
- CI uses PostgreSQL 16 and Redis 7.
- Alembic is tested through upgrade/current/downgrade/re-upgrade cycles.
- Keep Alembic revision identifiers at or below 32 characters unless the schema itself is deliberately migrated, because the existing `alembic_version.version_num` storage is 32 characters.
- `scripts/security-scan.sh` intentionally rejects secret-looking tracked material, including private keys, credential-bearing values and subscription/configuration URLs. Use obviously inert placeholders in tests/docs.
- Repository-wide frontend/site checks still run for bot-only changes. Do not edit website/app behavior merely to make a bot milestone easier.

## Provider and usage rules
- Certified real-provider behavior is currently Sanaei/3x-ui focused. Preserve provider-neutral domain contracts, but do not prematurely generalize unverified provider semantics.
- Usage synchronization is read-only and separate from the provider-write gate. Local service entitlement remains authoritative; provider counters are observations.
- Counter decreases, multi-attachment ambiguity, stale observations and insufficient confidence must fail closed/unknown according to existing usage policy.

## Documentation discipline
- `docs/ROADMAP.md` is the concise current roadmap. Update it when a milestone changes what is completed, next, later or deferred.
- Keep this file focused on stable agent rules/invariants. Put detailed feature history in the roadmap or dedicated feature docs instead of duplicating it here.
- Old milestone plans and README sections are historical context, not permission to remove newer production functionality.

## Definition of done
A change is done only when the implementation is coherent with current architecture, security/ownership/idempotency implications are handled, migrations are safe, focused tests exist, full required CI is green, relevant documentation is current, and no secret or customer-sensitive material is committed.
