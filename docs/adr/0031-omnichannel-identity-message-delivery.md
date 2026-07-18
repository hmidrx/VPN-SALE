# ADR — Milestone 5-E support decision

## Status
Accepted for Milestone 5-E.

## Decision
Support workflows use a backend-authoritative conversation/ticket model with explicit participant type, tenant, channel, visibility, idempotency and optimistic versioning. PostgreSQL is the durable source of truth; browser, Redis, realtime transports and Telegram are never authoritative.

## Consequences
- Customer/reseller ownership and agent permissions are checked server-side.
- Internal notes are agent-only and filtered before customer/reseller serialization.
- Messages are ordered by server sequence and revisions/redactions preserve history.
- SLA, assignment, escalation, CSAT, Telegram delivery and notifications emit durable/auditable records.
- Attachments use content validation, quarantine states and authorized download boundaries.
- Support macros and canned responses use allowlists only and cannot mutate finance, accounts, services or provider resources.
