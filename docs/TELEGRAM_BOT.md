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

Production conversation state uses `RedisConversationStore` with a 24-hour TTL. It stores only the current screen, an eight-entry navigation stack, active menu message id, version, and timestamps. Receipt bytes, card data, customer text, bot credentials, and database identifiers are never stored. A Redis outage therefore fails closed instead of silently switching to process memory.

The polling process uses the private `http://api:8000/api/v1/internal/telegram` bridge. Both services read a dedicated, root-owned `0600` token file mounted read-only at `/run/secrets/telegram-internal-token`; the bot token is never reused. The API compares the bearer credential in constant time, derives ownership from the authenticated Telegram subject, returns `private, no-store` responses, and exposes no database IDs. Caddy must not route `/api/v1/internal/telegram`. Rotate the credential by atomically replacing the file and restarting API and bot together.

Production and staging startup require the bridge URL, token file, and Redis URL and never fall back to the in-memory identity, portal, or conversation fixtures. Those implementations remain test-only. Rollback consists of stopping the bot before rolling back the API; no schema migration is introduced by this bridge.

The bridge reuses the customer service, wallet, notification-preference, and manual-topup application operations. Native top-up amount entry and confirmation are Redis-backed; confirmation creates one idempotent customer-owned request. Receipt photos and JPEG/PNG/WebP documents are size checked before Telegram `getFile`, downloaded only from Telegram's fixed HTTPS file host without redirects, and uploaded immediately for authoritative backend sanitization. Redis stores only the request reference and expected input, never card data or receipt bytes.

The wallet and top-up screens expose a native recent-request list and opaque-reference detail view. Receipt and cancellation controls are lifecycle-aware: local conversation cancellation never mutates a financial request, while request cancellation uses the sensitive callback policy and the authoritative private API before Redis flow state is cleared. Approved details keep the verified transfer, management gift, and total credited amount separate.

The bot image exposes the `vpn-sale-telegram-bot-v2-foundation` marker so test-server verification can confirm the deployed image contains the Bot V2 foundation.
