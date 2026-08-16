# BOT-3F — Durable support cursor pagination

BOT-3F removes fixed-window read limits from the durable support experience without changing support mutations, ownership rules, or the conversation lifecycle.

## Read contract

The existing support mutation endpoints remain unchanged. New additive read endpoints expose keyset pagination for:

- Telegram customer ticket lists;
- Telegram public ticket message history;
- Admin Web support inbox rows;
- Admin Web public message history;
- Admin Web internal-note history.

Conversation pages are ordered by `(updated_at DESC, reference DESC)`. Message pages use the durable per-conversation `sequence` as the keyset boundary and return each page in chronological display order.

## Cursor safety

Cursors are opaque, versioned and HMAC-SHA256 signed. Their signature is bound to the exact read surface and, where relevant, the ticket reference or status filter. A cursor from one ticket or filter cannot be replayed as a valid cursor for another surface.

Cursor payloads contain only navigation metadata:

- ticket pages: the public support reference and update timestamp;
- message pages: the durable message sequence.

Database primary keys, customer IDs, Telegram IDs, ticket subjects and message bodies are not placed in cursors. Ownership and RBAC checks are always evaluated again on every paged request; possession of a cursor grants no access.

## Telegram behavior

Telegram callback data never contains a cursor. The bot stores only the current/next cursor and a bounded eight-page navigation stack in its existing TTL-bound Redis conversation state. This keeps callback payloads below Telegram limits and prevents opaque navigation tokens from being exposed in button values.

The bot supports:

- newer/older ticket pages;
- newer/older message-history pages;
- latest-page CSAT only, so historical pages do not repeat rating controls.

No customer message body is added to conversation state.

## Admin Web behavior

The support console uses cursor-aware reads and exposes explicit load-more controls for:

- older inbox tickets;
- older public messages;
- older internal notes.

Cursors remain in component memory only. They are not persisted to localStorage or sessionStorage, and the client never decodes cursor contents.

After support mutations, the Admin client refreshes from the cursor-aware read endpoint so it does not depend on legacy bounded mutation projections.

## Compatibility and rollout

BOT-3F requires no database migration. Legacy read endpoints remain mounted for compatibility while Telegram and Admin Web move to the new pageable reads.

No deployment is performed by this increment. Environment rollout remains a separate operational action.