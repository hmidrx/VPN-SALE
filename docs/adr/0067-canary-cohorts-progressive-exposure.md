# ADR 0067: Canary cohort selection and progressive exposure

## Status
Accepted for Milestone 7-B.

## Decision
Cohorts are selected by typed eligibility rules and server-held HMAC percentage bucketing. Snapshots are immutable once a phase starts. Exposure is backend-authoritative and linked to release/configuration versions.

## Consequences
Customers cannot choose cohorts, raw customer-list uploads and arbitrary SQL filters are forbidden, and real-customer canary is disabled by default.
