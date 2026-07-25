# Telegram Bot

Telegram bot shell is aiogram-ready with Persian-only RTL customer text, menu architecture, deep links, optional Mini App launcher, throttling, callback ownership validation, retries, empty states, stale message handling, and future multi-brand support.

## Bot V2 foundation

Bot V2 makes Telegram the primary customer surface. New, auto-derived, and legacy customer language preferences are normalized to Persian; English customer screens and language switching are not supported. `/start` always renders a native Persian dashboard and does not depend on the customer website.

The dashboard is rendered by a screen renderer with typed screen identifiers (`home`, `buy`, `services`, `wallet`, `discounts`, `support`, `education`, `profile`, `settings`, `status`, `announcements`, `privacy`, and `help`). Primary buttons are compact two-column Telegram inline buttons; the optional web app entry is available only from Settings.

Callback data is versioned (`b:v1:<route>:<value>`), bounded to Telegram's 64-byte limit, and routed through an explicit callback route table. Malformed callbacks receive a Persian safe retry response. Stale language callbacks are acknowledged, do not mutate customer locale, and return a Persian stale-menu message with a single main-menu button. Polling acknowledges every callback query with `answerCallbackQuery`; callback screens only edit the originating message and never fall back to appending another chat message.

## Callback rate-limit policy

Callback limits are HMAC-scoped per Telegram user, so traffic from one customer cannot consume another customer's bucket. Safe reads and navigation (`nav`, Back, Home, Refresh/Retry, menu, Help, Privacy, Profile, Services/service details, Wallet, Support, Education, Status, Announcements, Settings, Notifications, Discounts, and the optional web entry) use a burst of 30 callbacks per 10 seconds. A limiter infrastructure outage fails open only for those read/navigation actions so customers are not locked out of menus.

Notification toggles use a mutation bucket of one accepted request per three seconds. Payment/service mutations, session revocation, account/profile changes, and any unknown future action use the sensitive bucket of 12 requests per 60 seconds; backend authentication, payment, ownership, and API rate limits remain unchanged. Limited writes fail closed, are acknowledged idempotently, and return at most one Persian callback alert (`لطفاً چند لحظه صبر کنید.`) in a three-second cooldown. No throttle response is appended to chat.

Telegram update IDs retain their 24-hour idempotency claim, while identical callbacks currently executing in one bot process are coalesced. Successful writes continue to use their update-derived idempotency key. Polling retries use bounded exponential backoff and do not alter callback or backend security limits.

The limits are configurable with the `VPN_SALE_TELEGRAM_NAVIGATION_*`, `VPN_SALE_TELEGRAM_MUTATION_*`, `VPN_SALE_TELEGRAM_SENSITIVE_*`, and `VPN_SALE_TELEGRAM_THROTTLE_NOTICE_COOLDOWN_SECONDS` environment variables. Restart the bot after a configuration change. Rollback is configuration-only for burst tuning; code rollback does not require a database or Redis migration and preserves existing PostgreSQL/Redis data. For local verification, populate the safe Telegram placeholders, select polling mode, then start the existing `telegram-bot` Compose service.

Conversation state uses the `ConversationStoreV2` abstraction, currently backed by a restart-friendly durable-memory implementation suitable for replacing with Redis. It stores only current screen, bounded navigation stack, active menu message id, version, update timestamp, and expiration timestamp. It does not store private customer message contents or sensitive callback payloads.

The bot image exposes the `vpn-sale-telegram-bot-v2-foundation` marker so test-server verification can confirm the deployed image contains the Bot V2 foundation.
