# ADR 0068: Rollout health gates, automatic pause and manual resume

## Status
Accepted for Milestone 7-B.

## Decision
Critical evidence, stale evidence, certification invalidation, unsafe capacity, security events and unresolved high-risk defects pause rollout automatically. Resume requires root-cause review, fresh gates, approval and exact plan confirmation.

## Consequences
Automation can pause but never silently advances, deletes provider identities, reverses payments or downgrades databases.
