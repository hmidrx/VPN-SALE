# UI-5 — Customer wallet and safe top-up

## Financial authority and customer DTOs

Wallet projections remain authoritative. The API validates `available + reserved = posted` and returns a maintenance error on disagreement; the browser repeats the validation and never repairs values. Customer responses intentionally omit wallet, customer, journal, posting, correlation, and provider identifiers. Bucket codes are translated through an allowlist with a safe fallback.

Transaction history uses a signed opaque cursor bound to the authenticated wallet. Ordering is descending by posting time and journal reference, so equal timestamps remain stable. Page size is bounded by wallet policy.

## Currency and payment restrictions

All API values and submissions are integer rial. Toman is a derived, explicitly labelled display only. TEST and default deployments expose no payment method unless it is active, configured, IRR-compatible, customer-channel compatible, and purpose compatible. Top-up creation remains unavailable with `PAYMENT_PROVIDER_NOT_CONFIGURED`; there is no placeholder redirect, synthetic success, provider write, or automatic wallet credit.

## Accessibility and responsive QA

The wallet uses semantic headings, RTL layout, isolated references, 44px controls, visible focus, textual status labels, reduced-motion handling, and horizontally scrollable tabs at 320px. Validate Android/iPhone mobile widths, Telegram Desktop, and wide desktop with both themes. Screenshot baselines should be captured once authenticated deterministic wallet fixtures are available.

## Rollout and rollback

Deploy the API before the customer application. Monitor projection mismatch and invalid cursor errors; never log cursors or credentials. Roll back the web bundle and API together if DTO validation errors rise. No migration or external provider configuration is introduced, so rollback does not require data changes.

Local startup remains `docker compose up --build`. Provider writes must remain disabled until a separately reviewed adapter rollout supplies credentials, host allowlists, webhook verification, and trusted settlement.
