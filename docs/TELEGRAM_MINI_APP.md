# Telegram Mini App

## Official client bridge initialization

The customer root layout loads `https://telegram.org/js/telegram-web-app.js?63` with Next.js `beforeInteractive`. This is customer-web-only and places the official bridge ahead of application hydration. The adapter reads only `Telegram.WebApp.initData`; `initDataUnsafe` is never an authentication input, and raw init data must not be logged, rendered, persisted, or attached to diagnostics.

The usual path detects the bridge synchronously. A 250 ms bounded, abortable, local-only readiness check protects against an unusual script initialization delay. Ordinary browser bootstrap remains first: an existing browser session can authenticate without Telegram, while a browser with neither a session nor the bridge remains `TELEGRAM_UNAVAILABLE`.

Roll out by building customer-web and running its production bridge regression before deployment, then use the test-server smoke check against the public customer HTML. Local verification is `npm run build -w @vpnsale/customer-web`, `npm run test -w @vpnsale/customer-web`, and `npx playwright test tests/e2e/telegram-bridge.spec.ts`. Roll back by reverting the bridge layout, readiness fallback, and associated checks together; no database, bot-menu, routing, or feature-flag rollback is required.

Mini App architecture includes init data auth, Telegram theme integration, safe areas, Back/Main buttons, haptics, mobile navigation, skeleton loading, connection-loss and session-expiry handling.

The customer shell uses the shared `@vpnsale/telegram-webapp` adapter as the single UI integration for theme, stable viewport height, safe areas, `ready()` and `expand()`. The older customer adapter remains only as a compatibility bridge for the unchanged server-validated authentication bootstrap; it must not become a second theme or storage implementation. Normal browsers receive dark-first design tokens and a safe no-Telegram fallback.
