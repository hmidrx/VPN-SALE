# ADR 0026: Customer Lifecycle and Security Controls

## Status
Accepted

Lifecycle commands use the existing `PENDING`, `ACTIVE`, `SUSPENDED`, `BLOCKED`, and `DEACTIVATED` state machine. There is no arbitrary status setter. Restrictive transitions revoke customer sessions server-side and append audit events. Unknown states fail closed.
