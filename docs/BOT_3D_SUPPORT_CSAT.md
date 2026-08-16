# BOT-3D — Native support CSAT

BOT-3D closes the native Telegram support loop with one durable customer-satisfaction response per support resolution cycle.

## Scope

- Reuse the existing Milestone 5-E `support_csat` table; no parallel survey store or migration is introduced.
- Expose a private service-authenticated Telegram API for CSAT eligibility and submission.
- A customer can submit a score from 1 through 5 only while the owned ticket is `RESOLVED` or `CLOSED`.
- The current resolution cycle is derived from durable `REOPENED` status-history transitions. Cycle zero is the initial resolution; each reopen creates a fresh future CSAT cycle.
- The database unique key `(conversation_id, resolution_cycle)` is the final idempotency anchor. Exact retries return the existing submission, while a different score or feedback for the already-submitted cycle is rejected.
- Optional feedback is normalized through the existing support-message sanitizer and bounded to 800 characters.
- Private responses use `Cache-Control: private, no-store` and expose only `eligible`, `submitted`, and the submitted score. Feedback is not echoed back through the Telegram bridge.

## Telegram UX and privacy

Resolved/closed tickets show five rating buttons only when the backend says the current cycle is eligible. Selecting a rating starts a bounded support flow that stores only the opaque ticket reference, selected score, flow type and stable idempotency key in conversation state. Customer feedback text is sent directly to the private API and is never persisted in Redis conversation state.

A customer can submit the score without feedback. If the transport outcome is ambiguous, the same request body and idempotency key are retained for a safe retry. Once the backend confirms submission, the flow state is cleared and the ticket displays the recorded score.

## Safety invariants

- Telegram identity is resolved to the internal customer before ticket ownership is checked.
- Other customers receive the same ticket-not-found boundary and cannot inspect or submit CSAT.
- Active/open/reopened tickets cannot accept CSAT.
- One submission is allowed for each resolution/reopen cycle.
- Feedback is not copied to logs, callback data, URLs or Redis state by BOT-3D.
- CSAT does not mutate wallets, payments, orders, services or provider resources.

## Validation

PostgreSQL coverage verifies eligibility, ownership, unsafe-feedback rejection, exact retry behavior, changed-payload rejection, and a second CSAT cycle after reopen and re-resolution. Telegram runtime coverage verifies rating presentation, feedback-free submission, feedback privacy in conversation state, flow cleanup, and stable retry keys across ambiguous outcomes.
