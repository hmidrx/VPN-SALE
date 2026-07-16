# Architecture

Modular monolith with strict boundaries. Clients call one backend. Domain/application code is independent of frameworks and providers. Critical events use transactional outbox. Idempotency protects payment, wallet, order, provisioning, webhook, refund, and reconciliation operations.
