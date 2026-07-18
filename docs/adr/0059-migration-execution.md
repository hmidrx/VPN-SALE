# ADR 0059-migration-execution: Milestone 7-A1 operations foundation

## Status
Accepted for Milestone 7-A1.

## Decision
VPN-SALE uses explicit LOCAL, TEST, CI, STAGING and PRODUCTION profiles. Staging mirrors production safety defaults, production fails closed, migrations run behind a deployment lock, observability/SLO evidence is version controlled, backups are encrypted and verified, DR values separate proposed from verified, live provider certification remains gated, and readiness reports never declare automatic production readiness.

## Consequences
Operators must provide real secret-manager values, staging provider panels and manual approvals before production release review. CI uses deterministic synthetic drills only.
