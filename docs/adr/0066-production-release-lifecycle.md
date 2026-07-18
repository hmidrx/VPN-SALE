# ADR 0066: Production release lifecycle and approval separation

## Status
Accepted for Milestone 7-B.

## Decision
Production rollout uses immutable plan versions bound to one finalized Release Candidate. Legal state transitions are domain methods only. Approval requires role separation, blocks self-approval, and invalidates stale plan digests.

## Consequences
There is no arbitrary production status setter. Operators must refresh evidence and re-approve material changes.
