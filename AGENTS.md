# AGENTS.md

## Purpose
This repository contains a modular monolith commerce platform for Telegram and web subscription sales of legitimate network-access services.

## Architecture boundaries
- Keep business rules in `packages/domain` and application use cases, not in FastAPI routes, aiogram handlers, React components, SQLAlchemy models, or provider clients.
- Core domain code must not depend on FastAPI, aiogram, SQLAlchemy, Telegram, 3x-ui, PasarGuard, or payment gateways.
- Use provider contracts in `packages/panel-adapters` and `packages/payment-adapters`; add real integrations only after exact API specs and test credentials are provided.

## Forbidden practices
- Do not access or modify external panel databases directly.
- Do not invent undocumented panel endpoints.
- Do not implement real commerce, real payment processing, or real provisioning during Milestone 0.
- Do not use floating point for money.
- Do not weaken linting, typing, authorization, or security checks to make tests pass.
- Never put try/catch blocks around imports.

## Security and secrets
- Never commit secrets, panel URLs, API keys, cookies, production credentials, real UUIDs, or subscription links.
- Redact secrets in logs and metrics.
- Store encrypted provider credentials in the database only with keys held outside the database.
- Use UTC timestamps and explicit audit logs for sensitive actions.

## Coding conventions
- Prefer explicit, small, cohesive modules.
- Python: Ruff formatting/linting, Pyright typing, pytest tests.
- TypeScript: strict mode, shared design tokens, RTL-ready layouts.
- Keep comments focused on why decisions exist.

## Migrations
- Alembic migrations must be deterministic, reviewed, reversible where possible, and must not contain real data or secrets.
- Database constraints and indexes are part of the design and must be documented.

## Testing requirements
- Unit tests must not perform real network calls.
- Use fake providers and deterministic fixtures.
- Add tests for state machines, idempotency, provider contracts, and security-sensitive flows as features are built.

## Required validation commands
- `docker compose config`
- `ruff format --check .`
- `ruff check .`
- `pyright`
- `pytest`
- `npm run lint`
- `npm run typecheck`
- `npm run test`

## Documentation updates
Update relevant docs and ADRs whenever architecture, security posture, dependencies, provider contracts, or operational behavior changes.

## Commit expectations
Commit cohesive changes on the current branch after validation. PR descriptions must list scope, tests, risks, and unresolved decisions.

## Definition of done
A change is done only when documentation, tests, linting, typing, security implications, rollback notes, and local startup instructions are updated and no secrets are committed.
