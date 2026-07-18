# ADR 0069: Rollback, database compatibility and provider certification boundaries

## Status
Accepted for Milestone 7-B.

## Decision
Application rollback deploys a previously verified immutable artifact only after schema compatibility checks. Database downgrade is not automatic. Provider production certification is distinct from staging and binds panel identity, endpoint identity, credential version, adapter version and contract digest.

## Consequences
Incompatible rollback becomes `FORWARD_FIX_REQUIRED`; financial records and provider-created identities remain durable and reconcile through explicit repair workflows.
