# Milestone 2-B2 Plan: Customer Catalog Storefront

Milestone 2-B2 adds the customer-web and Telegram Mini App storefront for real catalog discovery, fixed-plan selection, custom-plan building, server-authoritative non-persisted preview, immutable quote creation, quote detail, expiration handling, and bounded comparison. Checkout, wallet, orders, payments, providers, provisioning, subscription delivery, QR codes and service operations remain non-goals.

## Page inventory

- `/` storefront landing with real active categories and published products.
- `/catalog/categories` category browsing.
- `/catalog/products` searchable/filterable product listing.
- `/catalog/products/[productId]` product detail.
- `/catalog/products/[productId]/fixed` fixed-plan selection.
- `/catalog/products/[productId]/custom` custom-plan builder.
- `/catalog/compare` bounded comparison.
- `/catalog/quotes/[quoteReference]` immutable quote detail and expiration/recalculation state.
- Controlled states: unavailable product, paused/retired product, empty catalog, authentication required, suspended, blocked, network error, service unavailable, safe generic error and not found.

## Catalog discovery flow

```mermaid
flowchart TD
  A[Customer opens storefront] --> B[Bootstrap customer auth]
  B --> C{Authenticated?}
  C -- yes --> D[Load categories and products from /api/v1/catalog]
  C -- no --> E[Safe auth/browser fallback]
  D --> F[Normalize URL-safe filters]
  F --> G[Abort stale list requests]
  G --> H[Render category/product cards]
```

Only backend-supported filters are exposed: category, plan type and bounded localized search. Query strings contain only safe catalog identifiers and filters.

## Fixed-plan flow

```mermaid
sequenceDiagram
  participant UI as Customer Web
  participant API as Catalog API
  UI->>API: GET product detail/options
  UI->>UI: Normalize fixed traffic/duration/device/location/quality
  UI->>API: POST /api/v1/catalog/quotes/preview
  API-->>UI: Non-binding, non-persisted breakdown
  UI->>API: POST /api/v1/catalog/quotes with Idempotency-Key
  API-->>UI: Immutable quote reference
  UI->>API: GET /api/v1/catalog/quotes/{reference}
```

No client-supplied price is trusted and no order, wallet reservation, payment, service, allocation or provider request is created.

## Custom-plan state machine

```mermaid
stateDiagram-v2
  [*] --> Traffic
  Traffic --> Duration: valid bytes or explicit unlimited if allowed
  Duration --> Devices: valid day step
  Devices --> Location: valid integer count
  Location --> Quality: compatible option
  Quality --> Review
  Review --> Previewing: calculate price
  Previewing --> PreviewReady: latest response wins
  Previewing --> Review: validation/rate/service error
  PreviewReady --> Quoting: create immutable quote
  Quoting --> QuoteDetail
```

Traffic bytes, duration days and device counts are normalized as integers. Client validation is usability-only; backend validation remains authoritative.

## Authoritative pricing policy

The browser never calculates authoritative final prices. It may format integer rial/toman values returned by the backend and validates component sums for malformed responses. Preview uses the same server pricing engine as quote creation and is marked `binding: false` and `persisted: false`.

## Preview and quote distinction

```mermaid
sequenceDiagram
  participant UI
  participant API
  UI->>API: Preview normalized selection
  API-->>UI: Non-binding result, no DB quote
  UI->>API: Create quote with idempotency key
  API-->>UI: Persisted immutable quote snapshot
```

Preview responses cannot be reused as order prices. Final price locking occurs only in quote creation.

## Preview cancellation

```mermaid
flowchart LR
  A[Selection change] --> B[Abort previous AbortController]
  B --> C[Debounce/explicit calculate]
  C --> D[Request preview]
  D --> E{Response matches fingerprint?}
  E -- yes --> F[Show latest preview]
  E -- no --> G[Discard stale response]
```

## Quote idempotency

```mermaid
sequenceDiagram
  UI->>API: POST quote + customer-scoped key
  API->>API: Hash customer/key and fingerprint request
  alt same fingerprint
    API-->>UI: Existing quote
  else conflicting fingerprint
    API-->>UI: 409 idempotency_conflict
  end
```

## Quote expiration and recalculation

```mermaid
flowchart TD
  A[Load quote with server timestamps] --> B[Compute display countdown]
  B --> C{Server expiration passed?}
  C -- no --> D[Active quote notice]
  C -- yes --> E[Expired state]
  E --> F[Recalculate from immutable selected_options]
  F --> G[New preview]
  G --> H[New quote with new idempotency key]
```

Old quotes are never modified.

## Telegram Mini App integration

```mermaid
sequenceDiagram
  participant Bot
  participant TG as Telegram WebApp
  participant UI as Storefront
  Bot->>TG: Open allowlisted storefront URL
  TG->>UI: Theme, viewport, safe areas, initData
  UI->>UI: No SSR window access
  UI->>API: Existing customer auth flow
  UI->>TG: ready(), BackButton, MainButton where supported
```

Raw initData stays in memory for the existing auth bootstrap only; it is not logged, persisted, rendered or placed in URLs.

## Security boundaries

- Access tokens and CSRF values remain memory-only.
- Refresh credentials remain HttpOnly cookies.
- Quote references are identifiers, not authorization.
- Product/provider internals, panel URLs, server IPs, inbound IDs, SQL, pricing implementation objects and raw backend exceptions are never rendered.
- Account statuses fail closed for protected preview and quote operations.

## Accessibility

The storefront is RTL-first with semantic headings, keyboard-accessible cards/actions, labelled filters, screen-reader step progress, live regions for preview/quote results, visible focus indicators, reduced-motion-safe countdowns and LTR technical identifiers.

## Non-goals

Checkout, wallet, ledger, financial transactions, orders, invoices, payment gateways, refunds, provider instances, server/node/inbound management, allocation, provisioning, subscriptions, QR/config delivery, coupons, referrals, tickets, broadcasts, reseller commerce and analytics are not included.

## Acceptance criteria

Customers can browse real published categories/products, configure fixed and custom plans, receive non-persisted server previews, create immutable idempotent quotes, view quote breakdown/expiration, recalculate expired selections, compare up to three products, use the flow inside Telegram Mini App, and retain memory-only auth/initData handling with tests and documentation.
