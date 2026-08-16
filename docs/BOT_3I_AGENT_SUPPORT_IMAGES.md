# BOT-3I — durable agent-to-customer support images

## Goal

Complete the image-attachment support loop by allowing an authorized support agent to send a sanitized image from Admin Web to the customer’s Telegram conversation without bypassing the durable support message store, notification preferences, retry worker, optimistic locking or private-media controls.

BOT-3G already implemented customer-to-support images. BOT-3I adds the reverse direction only for JPEG, PNG and WebP images. Generic documents remain deferred until a scanning/quarantine pipeline exists.

## Admin upload contract

Admin Web uploads the raw image body to:

`POST /api/v1/admin/support-runtime/conversations/{reference}/attachments?expected_version={version}`

The request requires:

- an authenticated administrator with `support.attachments.manage`
- the same administrator to also have `support.reply`
- an `Idempotency-Key`
- one of the supported image content types
- the current conversation version for a new mutation

Requiring both permissions prevents attachment management from becoming an alternate public-reply channel.

The API reuses the private BOT-3G image pipeline: bounded streaming input, image verification, single-frame and dimension checks, decode/re-encode metadata stripping, opaque `SAT-*` references, private storage and SHA-256 recording. A successful new upload inserts a public `SUPPORT_AGENT` / `AGENT_ATTACHMENT` support message and its `support_attachments` row in the same database transaction, then advances the conversation version.

The image body and original filename are not stored in the notification outbox. The normalized server-generated filename is used for delivery.

Idempotency is content-bound. Replaying the same key and payload returns the original attachment even after the ticket version has advanced. Reusing the same key with different content returns a conflict instead of silently duplicating or replacing the first image.

## Durable notification path

Migration `0042_support_agent_image` extends the existing `enqueue_support_reply_notification` trigger so the existing payload-free `support_reply_notification_outbox` is populated for both:

- `AGENT_MESSAGE`
- `AGENT_ATTACHMENT`

Only public messages from a support agent to a customer conversation are eligible. The downgrade restores the previous text-only trigger.

The API never calls Telegram directly. This preserves the same transaction boundary and crash/retry behavior already used for text support replies.

## Worker delivery

The worker receives the private support-media volume read-only. Before calling Telegram `sendPhoto`, it revalidates the authoritative database rows and verifies that:

- the support message is public, unredacted and `AGENT_ATTACHMENT`
- the attachment belongs to that exact conversation and message
- the attachment state is `READY`
- its content type is still an allowed image type
- its byte size is within the support image ceiling
- the private file exists
- the file length exactly matches the database row
- the file SHA-256 exactly matches the recorded sanitized SHA-256

A missing or modified private file fails the event as invalid data and is never sent. Telegram network calls happen after the worker releases the database transaction.

Temporary Telegram failures keep the existing bounded retry/backoff behavior. Bot-disabled, unlinked, not-started, blocked-bot and customer preference opt-out conditions keep the existing skip behavior.

## Telegram privacy

Text support replies continue to send only a generic notification plus the support deep link. Agent images are sent as the sanitized private file with a generic caption and the same support deep link.

The notification caption does not copy ticket subjects, reply bodies, customer text or custom metadata. Logs retain only the existing event reference, attempt and safe delivery status.

## Admin Web

The support console can select one JPEG, PNG or WebP image and send it through the new durable endpoint. The action is enabled only while the selected ticket remains replyable. After success the console reloads the ticket so the new public attachment message, updated version and attachment list come from the server rather than optimistic browser state.

## Deployment

The normal Compose worker receives the existing private-media volume read-only. The restrictive test-server worker receives only the support-attachment volume, also read-only. The worker image prepares the same non-root private support mountpoint but does not create or chmod the mounted directory at runtime.

## Validation

BOT-3I coverage verifies:

- the Alembic revision identifier stays within the schema limit
- upgrade and downgrade trigger contracts
- agent upload creates exactly one public `AGENT_ATTACHMENT`
- the attachment row is `READY` and SHA-addressed
- the existing outbox is populated in the same durable flow
- ticket version increments once for the new upload
- identical idempotent replay does not add another message/outbox event
- mismatched idempotent replay is rejected
- worker source contract requires state/type/size/hash verification before `sendPhoto`

## Still deferred

Documents such as PDF, ZIP or arbitrary binary attachments are not part of BOT-3I. They require an explicit malware-scanning and quarantine pipeline before they should enter either customer or agent support flows.
