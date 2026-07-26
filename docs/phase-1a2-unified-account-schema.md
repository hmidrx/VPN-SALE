# Phase 1A.2.1 unified account foundation

## Existing identity audit

The Alembic head before this change is `0028_customer_notification_prefs`. `identity_users` is the customer identity root; `customer_profiles`, `telegram_accounts`, `customer_sessions`, and customer-facing commerce/support records reference it. Verified Telegram `initData` is the only enabled customer-account creation path. `telegram_accounts.username` is mutable Telegram presentation metadata, never a login identifier. Customer sessions store only refresh-token hashes and already implement token-family rotation, consumption, revocation, and reuse detection.

Administrators remain a separate `admins` email/password identity with `admin_sessions`. `roles` and `permissions` are connected to administrators through `admin_role_assignments`; before this revision they were not assignable to `identity_users`. Administrator TOTP secrets live encrypted in `totp_credentials`; `recovery_codes` contain hashes associated with those TOTP credentials. They are MFA recovery codes and must never be reused for account-password recovery.

References to `identity_users.id` include customer profiles, Telegram accounts, customer sessions, wallets, orders, support/customer-management, reseller, service, notification-preference and related customer-owned records. References to `admins.id` include admin sessions and role assignments, TOTP and MFA challenges, audit/security acknowledgement fields, and operational/admin attribution fields. The new assignment attribution foreign key does not change those authorization paths.

## Product and schema contract

One central `identity_users` row represents a person. Future username/password signup, verified-email recovery, Telegram linking, account recovery codes, and unified administrator authentication remain disabled and have no routes. Customer and reseller are additive roles on the same account. A Telegram numeric identity and a central account are mutually one-to-one; Telegram usernames remain metadata.

`account_credentials` is one-to-one by its `user_id` primary key (`ON DELETE RESTRICT`). It stores a 4-32 character ASCII username, its lowercase canonical key, an Argon2id hash, password/change/login timestamps, non-negative failed count, positive version, and timestamps. Canonical usernames are unique. No Telegram or administrator value is copied.

`account_emails` has a UUID primary key, unique restricted `user_id`, globally unique normalized email, nullable verification time, and timestamps. Only `verified_at IS NOT NULL` can make it eligible for a future recovery implementation; no challenge or delivery exists.

`user_role_assignments` has a composite primary/unique key `(user_id, role_id)`, assignment time, and nullable assigning administrator. User deletion cascades assignments, role deletion is restricted, and administrator deletion sets attribution null. Existing admin authorization continues to use `admin_role_assignments`.

`admins.user_id` is nullable, unique, and restricted to `identity_users.id`. It moves no hashes and changes no login, MFA, session, token, cookie, CSRF, or JWT behavior. The unique Telegram `user_id` index allows multiple nulls on PostgreSQL while enforcing one linked Telegram record per account.

## Migration, rollback, and operations

Upgrade first checks only for the existence of duplicate non-null Telegram ownership and emits no identifiers or profile data. It refuses inconsistent data, directly adds the tables/column/constraints/index, idempotently ensures `customer`, `reseller`, `support`, `admin`, and `super_admin`, preserves every other role/permission, and inserts exactly one customer assignment per existing user with `ON CONFLICT DO NOTHING`.

Downgrade refuses if credentials, emails, admin links, or any non-customer account-role assignments exist, because removing them would silently lose data. Otherwise it removes only this revision's tables, admin bridge, and unique Telegram index (restoring the old non-unique index). Seeded roles are deliberately preserved because deleting shared role rows would be unsafe. Roll back the application first; inspect and explicitly evacuate unified data before retrying downgrade.

All six capability flags default to false and startup fails closed if any is enabled while its implementation is incomplete. Local startup remains `docker compose up --build`; production-like deployments must also leave these flags false. This phase has no HTTP/UI behavior and no external provider, payment, email, Telegram bot, or provisioning writes.
