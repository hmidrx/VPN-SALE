# Milestone 5-D — Reseller Web Portal

## Scope
Milestone 5-D delivers the production-grade reseller-web surface on top of the Milestone 5-C reseller domain and APIs. The portal covers authentication bootstrap, account-status handling, dashboard, managed customers, wholesale catalog, authoritative pricing, quote creation, reseller-funded checkout, prepaid wallet, controlled credit, financial history, safe remarks, reseller-scoped branding, activity, security, tests, and documentation.

## Route inventory
- `/` hosts the authenticated reseller shell and anchors for Dashboard, Catalog, Customers, New order, Orders, Wallet and credit, Pricing, Remarks, Brand, Activity, and Profile/security.
- Route guards must resolve reseller authentication, CSRF readiness, account status, maintenance state, and capability-aware navigation before mutations are enabled.
- Future nested routes must keep the same customer/reseller/admin context separation and must not add impersonation.

## Tenant isolation
The reseller context is authoritative. Customer directory, quotes, orders, wallet, credit, branding, activity, sessions, and safe profile fields are loaded only through reseller-scoped APIs. The UI never exposes customer sessions, Telegram initData, administrator notes, Security Center internals, another reseller's ownership history, raw tokens, or token hashes.

## Pricing authority and checkout
Backend pricing is authoritative. The frontend displays integer rial returned by the API and derives toman only as a labeled presentation value. Resellers never submit trusted wholesale totals, discounts, wallet balances, credit utilization, or ledger effects. Quote and order views preserve immutable pricing snapshots, pricing versions, expiration, payment source, payer reseller, and beneficiary customer. PREPAID and CREDIT checkout are mutually exclusive and one checkout creates one order and one financial effect.

## White-label boundaries
Reseller branding is scoped to reseller-web presentation only. Safe fields include display brand, short name, validated accent token, approved support URL, footer text, logos when validated by the backend, and future custom-domain request preparation. Arbitrary CSS, JavaScript, raw HTML, external fonts, callbacks, and fake custom-domain activation are outside scope.

## Remark safety
Remark templates use only backend-registered placeholders such as `{reseller_brand}`, `{customer_label}`, `{product_name}`, `{location}`, `{order_short_id}`, `{service_short_id}`, and `{sequence}`. Unknown placeholders, control characters, scripts, URLs, credentials, tokens, and provider/configuration data are rejected. Remark changes affect presentation only and cannot alter UUID, Address, Host, SNI, Path, protocol, transport, security, or provider identity.

## Browser storage policy
Access tokens remain memory-only. Refresh tokens and CSRF material follow the existing HTTP-only/session architecture. The reseller app must not persist tokens, Telegram initData, reseller profile, customers, prices, quotes, orders, wallet/credit data, remark templates, branding drafts, idempotency keys, or full API responses in localStorage, sessionStorage, or IndexedDB. Safe list filters may appear in URLs.

## Accessibility
The shell is Persian RTL by default, responsive, keyboard navigable, focus-visible, screen-reader labeled for financial values, and reduced-motion aware. Status is communicated with text as well as color. Technical references remain LTR.

## Acceptance criteria
1. ACTIVE resellers can enter the portal and inactive statuses are safely blocked from mutations.
2. Dashboard, catalog, customers, orders, wallet/credit, remarks, branding, activity, and profile/security are represented without fake provider data.
3. Rial is authoritative and toman is explicitly presentation-only.
4. READY_FOR_FULFILLMENT is explained as paid but not delivered, with no service, QR, subscription, or configuration output.
5. Tenant isolation, idempotency, ledger-backed financial effects, and credit-limit enforcement remain backend-owned.
6. No sensitive reseller, customer, auth, financial, quote, or order data is persisted in browser storage.
