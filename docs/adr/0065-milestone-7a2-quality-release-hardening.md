# ADR 0065: Milestone 7-A2 quality and release hardening

## Status
Accepted

## Context
Release review needs reproducible evidence for performance, security, reliability and operational recovery without targeting production or fabricating unavailable staging results.

## Decision
Use repository-native Python domain rules plus opt-in documented profiles. Quality tooling stores bounded metadata only: sanitized references, digests, states and typed defect records. Ordinary CI runs only `CI_SAFE`; high-load, DAST and chaos profiles require allowlisted staging origins and typed confirmation.

## Consequences
- `NOT_RUN`, `FAILED`, `BLOCKED` and `EXPIRED` remain distinct release-gate states.
- Critical/High defects block release until regression evidence verifies the fix.
- RC provenance binds commit, application version, migration head and immutable artifact digests; mutable `latest` is not authoritative.
- Admin-web displays quality/release evidence but cannot execute arbitrary commands or deploy production.

## Methodology decisions
- Performance architecture: versioned workload profiles with warm-up, ramp, bounded duration, cool-down and invariant checks.
- Workload/data isolation: all actors use `m7a2-*` tenant prefixes and synthetic identities.
- Acceptance budgets: p95/p99/error/timeout/queue/outbox budgets derived from SLOs and staging resources.
- Chaos boundaries: isolated, time-bounded, automatically cleaned up; no production faults.
- Security assessment: manual review plus isolated DAST; scanner output is supporting evidence only.
- Release blockers: Critical/High, security bypasses, failed restore, duplicate financial/provider side effects and tenant leaks block review.
- Go/No-Go: no automatic production GO; output is `NO_GO`, `READY_FOR_RC_REVIEW` or `READY_FOR_CONTROLLED_CANARY_REVIEW` only.
