# Telegram Mini App

Mini App architecture includes init data auth, Telegram theme integration, safe areas, Back/Main buttons, haptics, mobile navigation, skeleton loading, connection-loss and session-expiry handling.

The customer shell uses the shared `@vpnsale/telegram-webapp` adapter as the single UI integration for theme, stable viewport height, safe areas, `ready()` and `expand()`. The older customer adapter remains only as a compatibility bridge for the unchanged server-validated authentication bootstrap; it must not become a second theme or storage implementation. Normal browsers receive dark-first design tokens and a safe no-Telegram fallback.
