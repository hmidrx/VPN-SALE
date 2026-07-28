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
