# BOT-3H — durable support canned responses and safe macros

## Goal

Finish the remaining Milestone 5-E support productivity workflow by making the existing canned-response and macro schema usable from the durable Admin support runtime without weakening RBAC, ticket lifecycle validation, optimistic locking or auditability.

## Existing schema

BOT-3H intentionally does not add a database migration. Milestone 5-E already created:

- `support_canned_responses`
- `support_macros`
- `support.canned_responses.read`
- `support.canned_responses.manage`
- `support.macros.read`
- `support.macros.manage`

The runtime now maps and uses those existing tables. Alembic head remains `0041_support_sla_escalations`.

## Canned responses

Canned responses are immutable revisions. A new definition starts at version 1; editing creates a new row with the next version rather than overwriting historical content. Listing resolves only the newest revision for each `(code, locale)` pair, so disabling a newer revision never falls back silently to an older active definition.

A response can optionally be restricted to one support queue, one category, or both. Rendering against a ticket rechecks that scope on the server.

Template placeholders use the explicit `{{placeholder_name}}` form. The definition must declare the exact placeholder set present in the body. Four built-in placeholders are supplied from the authoritative ticket row:

- `ticket_reference`
- `subject`
- `status`
- `priority`

Other declared placeholders must be supplied explicitly by the agent UI. Built-in values cannot be overridden by the browser. Supplied values and the final rendered response pass through the support text sanitizer and bounded length checks.

Rendering increments the version-specific `usage_count` and writes a privacy-safe audit event. The rendered text is only a draft; the existing `/reply` endpoint remains the only path that sends the response to the customer.

## Macros

Macros are also immutable revisions. BOT-3H supports at most one action of each safe draft type:

- `reply_draft`
- `internal_note_draft`
- `status_draft`

Macro text may use only the four authoritative built-in ticket placeholders. A preview request requires the current ticket version and validates the proposed status against the existing `LEGAL_TRANSITIONS` state machine.

Most importantly, macro preview never writes a support message, internal note, assignment or ticket status. It only returns draft values to Admin Web. The agent must still use the existing reply, internal-note and status endpoints, so their original permissions, idempotency rules, replyability checks and optimistic version checks remain authoritative. This prevents `support.macros.read` from becoming a privilege-escalation path.

## Admin Web

Opening a ticket now loads only canned responses that are active and in scope for that ticket. The console renders inputs for custom placeholders and can insert the server-rendered result into the existing reply editor.

The console also lists active macros. Applying a macro fills any reply draft, internal-note draft and legal status/reason fields returned by the server. A visible notice tells the operator that nothing is sent automatically.

If the administrator lacks canned-response or macro read permission, the existing support console remains usable and simply omits those productivity tools.

## Audit and privacy

Canned definition creation/revision, canned rendering, macro creation/revision and macro preview emit admin audit events. Audit metadata contains only resource code/version and ticket reference where relevant; canned body text, macro body text and custom placeholder values are not copied into audit metadata.

All list/render/preview responses use private no-store semantics where a response object is available.

## Validation

The PostgreSQL integration coverage verifies:

- ticket-scoped canned-response listing
- built-in plus custom placeholder rendering
- version-specific usage counting
- immutable canned-response revision creation
- macro revision creation
- reply and status draft rendering from authoritative ticket values
- macro preview leaves the ticket status and version unchanged

## Deferred

Visual authoring/management screens for creating canned responses and macros, richer search/favorites, per-agent usage analytics, approval workflows and direct multi-operation macro execution are intentionally separate increments. Direct macro execution should only be considered with per-action authorization, idempotency and transactional conflict semantics equivalent to the underlying privileged endpoints.
