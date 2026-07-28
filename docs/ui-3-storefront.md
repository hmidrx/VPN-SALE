# UI-3 customer storefront

## Scope and behavior

UI-3 replaces the legacy catalog presentation with customer-scoped page, toolbar, card, builder,
comparison, quote, and inline-state compositions. API contracts, authoritative pricing,
authentication, checkout, payment, wallet, and provisioning behavior are unchanged.

The former catalog state reused `.state`, whose minimum height is an authentication-shell viewport.
Nested inside the authenticated customer shell, that pushed useful empty/error copy toward the
fixed navigation. Catalog routes now use `.catalog-inline-state`, a content-sized surface, while
card skeletons keep loading layouts stable.

Search remains local to the already-loaded API response. Category chips are rendered only from API
categories. Escape and the contextual clear action reset local search without reloading. Product
names prefer translated API names; safe neutral fallbacks never invent a plan, feature, or price.
The browser displays server-provided price values and only validates component integrity. An invalid
component sum fails closed instead of exposing technical details or a potentially misleading total.

## Accessibility and responsive QA

- Persian RTL composition, semantic headings, labelled controls, visible focus, `aria-live` states,
  reduced-motion skeletons, and 44px minimum controls are retained.
- Mobile uses one-column cards and safe bottom padding above the five-item navigation; the padding is
  removed when desktop navigation replaces it.
- Layout breakpoints cover 320–430px phones, 768px tablets, and centered 1024–1440px desktop views.
- Long translated names wrap safely, descriptions clamp, and horizontal category filters scroll
  within their toolbar rather than expanding the viewport.

## Local startup and visual review

Run `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true npm run dev -w @vpnsale/customer-web`, then open a catalog
route through the preview authentication mode. Playwright uses deterministic mocked catalog data;
it must never contact an external service.

## Security, rollout, and rollback

No secret-bearing fields, raw failures, internal identifiers as headings, or new persistence are
introduced. Roll out as a customer-web-only deployment after frontend, security, Python, Compose,
and restrictive checkout acceptance checks pass. Roll back by deploying the preceding customer-web
artifact; there are no migrations, API changes, cache transitions, or data cleanup steps.
