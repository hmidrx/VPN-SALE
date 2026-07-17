# ADR 0009: Catalog and Pricing Architecture

## Status
Accepted for Milestone 2-A.

## Decision
Catalog APIs call authentication/authorization dependencies, then catalog application code, domain value objects and repository-backed SQLAlchemy persistence. Pricing rules live in `packages/domain` and are side-effect-free, typed, ordered and explainable. Pydantic schemas and ORM models remain separate.

## Consequences
Routes stay thin, quotes do not mutate wallet/order/provider state, and future bot/frontend clients consume normalized catalog view models only.
