# HYPERCARE

Milestone 7-B defines this operating area in `docs/milestones/MILESTONE_7_B_PLAN.md`. Real production actions are operator-only, protected by environment approval, typed confirmation, separate approval and immutable sanitized evidence. Codex/CI evidence that needs production access remains `NOT_RUN` or `BLOCKED`, never success.

Key safety rules:
- no production secrets, endpoint dumps, provider credentials, subscription tokens or customer cohort identities in Git, logs, reports, APIs or browser storage;
- immutable Release Candidate and artifact/schema/provider-contract digests are authoritative, never mutable `latest` tags;
- phase advancement is manual and backend-authoritative;
- rollback does not delete orders, invoices, ledger entries, provider identities or services;
- database downgrade is never automatic;
- provider writes require exact production certification and separate write-enable approval.
