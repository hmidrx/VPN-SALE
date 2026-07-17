# ADR 0025: Customer Administration Platform

## Status
Accepted

## Decision
Build customer administration as thin permission-protected APIs over existing identity, session, wallet, ledger, commerce, audit and Security Center models. New persistence is limited to internal notes/history, tags/assignments, saved views, adjustment requests, export jobs and bulk jobs/items.

## Consequences
Customer APIs do not receive notes, tags do not alter roles/prices/balances, exports are allowlisted and short-lived, and bulk jobs execute the same domain commands as individual operations.
