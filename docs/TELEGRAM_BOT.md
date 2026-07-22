# Telegram Bot

Telegram bot shell is aiogram-ready with Persian-only RTL customer text, menu architecture, deep links, optional Mini App launcher, throttling, callback ownership validation, retries, empty states, stale message handling, and future multi-brand support.

## Bot V2 foundation

Bot V2 makes Telegram the primary customer surface. New, auto-derived, and legacy customer language preferences are normalized to Persian; English customer screens and language switching are not supported. `/start` always renders a native Persian dashboard and does not depend on the customer website.

The dashboard is rendered by a screen renderer with typed screen identifiers (`home`, `buy`, `services`, `wallet`, `discounts`, `support`, `education`, `profile`, `settings`, `status`, `announcements`, `privacy`, and `help`). Primary buttons are compact two-column Telegram inline buttons; the optional web app entry is available only from Settings.

Callback data is versioned (`b:v1:<route>:<value>`), bounded to Telegram's 64-byte limit, and routed through an explicit callback route table. Malformed callbacks receive a Persian safe retry response. Stale language callbacks are acknowledged, do not mutate customer locale, and return a Persian stale-menu message with a single main-menu button. Polling acknowledges every callback query with `answerCallbackQuery` before rendering or fallback message delivery.

Conversation state uses the `ConversationStoreV2` abstraction, currently backed by a restart-friendly durable-memory implementation suitable for replacing with Redis. It stores only current screen, bounded navigation stack, active menu message id, version, update timestamp, and expiration timestamp. It does not store private customer message contents or sensitive callback payloads.

The bot image exposes the `vpn-sale-telegram-bot-v2-foundation` marker so test-server verification can confirm the deployed image contains the Bot V2 foundation.
