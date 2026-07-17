# Milestone 1C-B2 Plan — Telegram Bot Foundation

## Scope
Implement the production-oriented Telegram bot foundation only: disabled, polling and webhook modes; secure webhook secret validation; `/start` identity registration through application use cases; professional Persian customer menu; Mini App WebApp launch URLs; localization; update idempotency; bot rate limiting; observability and health/readiness surfaces.

## Non-goals
Products, pricing, wallet, ledger, orders, payments, panel adapters, provisioning, subscriptions, tickets, broadcasts, referrals, resellers, servers, nodes, inbounds, QR codes and provider API calls are explicitly out of scope.

## Architecture
```mermaid
flowchart LR
  Telegram[Telegram update] --> Router[aiogram router/handler]
  Router --> Command[Typed internal command]
  Command --> UseCase[Bot application use case]
  UseCase --> Port[Identity/repository port]
  Port --> Adapter[Infrastructure adapter]
```
Handlers translate Telegram data into typed commands and must not import SQLAlchemy models, open database sessions, query Redis directly, call provider APIs, or contain commerce/provisioning rules.

## Runtime modes
- **disabled**: default, no Telegram network calls, honest health state for CI and Docker verification.
- **polling**: explicit local development mode, configurable allowed updates and timeout, rejected in production-like environments unless policy explicitly allows it.
- **webhook**: production-oriented POST endpoint with HTTPS URL validation, constant-time `X-Telegram-Bot-Api-Secret-Token` checks, request-size limits, idempotency and fast acknowledgement.

## `/start` sequence
```mermaid
sequenceDiagram
  participant T as Telegram
  participant H as Bot handler
  participant I as Idempotency
  participant U as Identity use case
  participant M as Menu registry
  T->>H: /start update
  H->>I: claim(update_id)
  I-->>H: first update
  H->>U: RegisterOrUpdateTelegramBotUser
  U-->>H: status + locale
  H->>M: visible menu items
  H-->>T: localized welcome + WebApp menu
```

## Duplicate handling
```mermaid
flowchart TD
  A[Webhook update_id] --> B{Atomic claim}
  B -->|first| C[Process side effects]
  B -->|duplicate| D[Acknowledge without sends]
```

## Mini App launch
```mermaid
flowchart LR
  Menu[Menu item] --> Builder[Allowlisted URL builder]
  Builder --> WebApp[Telegram WebAppInfo button]
  WebApp --> Backend[Existing Mini App auth verifies initData]
```
No tokens, initData, Telegram IDs, usernames, emails or internal UUIDs are placed in URLs.

## Blocked bot handling
```mermaid
sequenceDiagram
  participant TG as Telegram send
  participant EH as Error handler
  participant UC as Application service
  TG-->>EH: forbidden / bot blocked
  EH->>UC: mark bot blocked safely
  UC-->>EH: sanitized event
  Note over UC: later valid incoming update clears flag
```

## Acceptance criteria
The bot supports all required commands, idempotent `/start`, menu extensibility, webhook secret validation, Mini App URL allowlisting, localization fallback, HMAC-hardened rate-limit keys, safe logs/metrics, Docker optional operation without real credentials and no commerce/provider functionality.

## Risks and mitigations
- Telegram network calls in tests are avoided with deterministic fakes.
- Redis outages fail closed in production design; in-memory fakes are test-only.
- Legal privacy copy is concise and marked for final legal review.
