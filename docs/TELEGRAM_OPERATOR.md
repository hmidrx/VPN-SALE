# Telegram operator console

The Telegram operator path is a **read-only operational triage surface** layered on the existing admin authority model. It does not create a second administrator account system and it does not trust a configured/raw Telegram ID allowlist.

## Access model

An operator opens the hidden `/ops` command in the existing Telegram bot. Access succeeds only when all of these are true:

1. the bot authenticates to the private API with the existing internal service credential;
2. the request carries the Telegram subject supplied by the trusted bot transport;
3. `telegram_accounts.telegram_user_id` resolves to a linked `identity_users` row;
4. an `admins` row references that **same** `identity_users` row;
5. the administrator status is `ACTIVE`;
6. the administrator's existing active role assignments grant `ops.telegram.read`.

The `0049_tg_operator_perm` migration adds `ops.telegram.read` and grants it to the built-in `super_admin` role when that role exists. Other roles receive no operator access unless an administrator explicitly grants the permission through the existing role/permission system.

A missing link, inactive administrator or missing permission returns the same customer-safe denial. Telegram never learns which authority check failed.

## Linking an administrator

Do not create a separate trusted-Telegram-ID configuration and do not patch Telegram IDs into source code. The intended authority link is the existing identity graph:

```text
TelegramAccountModel.user_id
        │
        └── identity_users.id ── AdminModel.user_id
```

The Telegram account therefore needs to be linked to the same underlying identity user already owned by the administrator. Once the administrator is active and has `ops.telegram.read`, `/ops` becomes available automatically.

## Current operator scope

Version 1 is deliberately read-only. `/ops` shows only bounded aggregate operational information already produced by the existing health collector:

- overall `HEALTHY` / `DEGRADED` / `ACTION_REQUIRED` state;
- main worker liveness and consecutive cycle failures;
- due/retrying/failed/stale-claim outbox counts;
- fulfillment retry/block/review/failure counts;
- paid service-operation in-progress/review-required counts;
- authoritative usage-sync status and stale/degraded counts;
- a fixed allowlist of safe operational signal codes translated to Persian.

The refresh button is a native Telegram callback and performs another read. It does not mutate durable work.

## Information that must never enter the console

The operator response and Telegram renderer must not include:

- customer IDs or arbitrary customer Telegram IDs;
- provider/panel endpoints or remote client identities;
- provider credentials, vault keys, passwords or tokens;
- subscription/config connection material;
- raw exception text, raw provider responses or database URLs;
- hostname/PID/worker-instance identifiers.

The bot-side adapter accepts only the fixed status/signal vocabulary and bounded non-negative aggregate counts. Arbitrary API response text is rejected rather than rendered.

## Future operator mutations

Do not add a generic `retry`, `approve`, `fix`, `credit` or provider-mutation command directly in Telegram. A future Telegram operator mutation is acceptable only when all of the following already exist on the backend:

- an explicit admin permission;
- the authoritative business rule and ownership/safety checks;
- an audit trail;
- approval/step-up requirements when the existing admin path requires them;
- idempotency/reconciliation semantics appropriate to the mutation.

Telegram should call that backend operation; it must not reimplement the financial/provider rule locally. High-risk unresolved service/provider states remain manual-review/reconciliation states, not one-tap Telegram retries.
