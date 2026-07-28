# UI-5.1 — premium Toman-first customer wallet

## Diagnosis and scope

The previous mobile wallet treated every balance projection, bucket, reservation, and policy value as an equal card. Five primary links wrapped on narrow screens, technical identifiers reached customers, and amounts repeated both Rial and derived Toman. The redesigned customer wallet uses one available-balance hero, three primary destinations, three recent transactions, and a collapsed details area. Credits, reservations, and policy remain reachable as secondary pages.

This is a presentation-only rollout. Database and API amounts remain authoritative integer Rial fields. No provider, payment success path, wallet credit, redirect construction, or browser balance authority is enabled.

## Exact conversion boundary

`wallet/format.ts` validates every received Rial amount as a nonnegative safe integer and requires exact divisibility by ten. A remainder raises `NON_EXACT_TOMAN_AMOUNT`; the UI fails closed rather than rounding. Toman input accepts Persian, Arabic, and Latin digits plus ordinary grouping separators, while rejecting signs, decimals, scientific notation, empty/zero input, text, and unsafe integers. The safe integer Toman value is multiplied by exactly ten before `amount_rial` is serialized.

## Customer experience and accessibility

All customer wallet and payment amounts render exactly one Persian-localized `تومان` label. Zero buckets and zero reservation summaries are suppressed. The 3-column primary navigation remains a single row at 320 px. Controls have 44 px targets, focus rings, semantic labels, RTL layout, bounded live copy feedback, reduced-motion behavior, and mobile bottom-navigation clearance.

Without an available method, amount entry, policy validation, quick amounts, and support remain useful, but no create button is rendered and no POST can occur. A configured deterministic method exposes review only after valid input; changing the amount invalidates review and rotates the idempotency operation.

## Operations

Local startup remains `npm run build --workspace=@vpnsale/customer-web` followed by the existing customer-web start command. Roll out as the customer frontend artifact only. Roll back by deploying the preceding frontend artifact; there is no migration or server rollback. Real payment-provider integration remains deferred until documented contracts and credentials are supplied.

## UI-5.2 — final mobile input polish

Android review found that selecting the 100,000-Toman preset left the editable field as raw `100000`. The field now keeps canonical ASCII digits as its internal model while rendering Persian digits and the Persian thousands separator (`۱۰۰٬۰۰۰`). Persian, Arabic, and Latin digits and grouping-only paste are normalized; currency copy, signs, decimals, exponents, arbitrary text, and values that cannot be multiplied safely by ten are rejected rather than truncated. Empty input remains empty. The separate Toman suffix is unchanged, and the serialized request for 100,000 Toman remains the exact integer `{ "amount_rial": 1000000 }`.

Preset selection updates the editable value, preserves focus without scrolling, exposes exactly one `aria-pressed` state, and resets review, redirect action, and the idempotent operation. Manual edits retain that state only while the canonical value still matches. The field uses a text control with a numeric input mode so mobile keyboards are available without browser number spinners.

Telegram Desktop review also identified browser-like refresh controls and excess transaction-empty space. Overview and transaction history now share an inline-SVG refresh control with a 44 px target, accessible label, duplicate-request guard, bounded live feedback, and reduced-motion behavior. Empty history has a compact icon, explanation, and top-up action. The no-method message remains a quiet, compact support path and does not render or invoke top-up submission.

Wallet scroll clearance now combines the actual mobile navigation reservation, Telegram/iPhone safe-bottom inset, and 20 px breathing room; desktop drops that reservation. Deterministic Playwright coverage captures Android, iPhone, narrow Telegram Desktop, and 1024×768, 1280×800, and 1440×900 layouts and checks overflow, selected input presentation, minimum-only copy, no-method POST safety, control sizing, and bottom-navigation separation.

Roll out only the customer-web artifact. Roll back to the UI-5.1 frontend artifact if input or layout regressions appear. No API, database, provider, payment authority, wallet policy, session behavior, or migration changes are included. Local startup remains `npm run build --workspace=@vpnsale/customer-web` followed by `npm run start --workspace=@vpnsale/customer-web`.
