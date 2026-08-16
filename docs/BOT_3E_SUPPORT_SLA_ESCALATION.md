# BOT-3E — Durable Support SLA Escalation

BOT-3E closes the operational gap between stored support SLA deadlines and manager action. It adds a durable escalation history, a bounded PostgreSQL worker, minimal manager-notification records and explicit admin operations without changing customer-visible ticket content or provider/payment state.

## Runtime rules

- PostgreSQL is authoritative. The worker uses bounded `FOR UPDATE SKIP LOCKED` scans so multiple workers can coexist without processing the same conversation row concurrently.
- Terminal tickets (`RESOLVED`, `CLOSED`, `SPAM`, `ARCHIVED`) are excluded.
- When the SLA snapshot pauses clocks while waiting for the customer, `WAITING_FOR_CUSTOMER` is excluded from automated escalation until the existing support lifecycle resumes its deadlines.
- First-response debt exists until the first non-redacted public support-agent message.
- Next-response debt exists only after at least one agent response and when the newest public customer message is newer than the newest public agent message. Its deadline is derived from the durable customer-message timestamp plus the snapshotted `next_response_minutes`, avoiding the stale initial next-response timestamp.
- Resolution debt uses the authoritative `resolution_deadline` already maintained by the support lifecycle.
- `AT_RISK` is the final 20 percent of the applicable SLA duration, bounded to 1–60 minutes. `BREACHED` wins once the deadline has passed.

## Dedupe and history

Automated escalation identity is unique by `(conversation_id, kind, phase, deadline_at)`. Exact rescans converge on the existing row. If an SLA deadline legitimately moves after a paused customer-wait period, the new deadline forms a new operational cycle and may create a new escalation.

Manual escalations use the existing `support.escalate` permission and are intentionally separate from ticket status. An SLA escalation is an operational signal, not an implicit lifecycle transition. Operators may acknowledge an escalation without rewriting the conversation state.

## Privacy boundary

Manager notification records contain only opaque ticket/escalation references and operational metadata: kind, phase, deadline and priority. Ticket subject, customer identity, Telegram identity and support message bodies are not copied into the escalation notification payload.

## Admin operations

The admin API exposes:

- open/all SLA escalation inboxes under `/api/v1/admin/support-runtime/sla/escalations`;
- per-ticket escalation history;
- explicit manual escalation with optimistic ticket-version checking;
- idempotent acknowledgement of an open escalation.

Existing permissions `support.sla.read` and `support.escalate` remain authoritative. No new permission seeds are required.

## Rollback

Migration `0041_support_sla_escalations` adds only the escalation history table and indexes. Downgrade removes those objects and leaves conversations, messages, support notifications, CSAT and Telegram reply delivery unchanged.
