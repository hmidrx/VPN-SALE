# Architecture

Modular monolith with strict boundaries. Clients call one backend. Domain/application code is independent of frameworks and providers. Critical events use transactional outbox. Idempotency protects payment, wallet, order, provisioning, webhook, refund, and reconciliation operations.

## Milestone 1A identity module boundaries

Identity domain objects live in `packages/domain` without FastAPI, SQLAlchemy, Telegram, Redis, or provider dependencies. Application-facing repository protocols expose domain objects only. SQLAlchemy models under the API package provide persistence mapping and constraints but do not contain business rules. Cryptographic infrastructure is isolated from domain entities so later use cases can depend on interfaces rather than framework routes.
