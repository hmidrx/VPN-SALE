# UI-4: customer services center

## Scope and safety

The former `/services` placeholder is replaced by a mobile-first list and a single detail route with overview, connection, usage, management, and activity sections. Customer-facing lifecycle labels are centralized and unknown values render as «در حال بررسی».

Service reads derive customer ownership from the authenticated customer session and return `404` for unowned public references. Required verified attachment totals are counted from service attachments; attachment and provider identifiers never enter the response. Entitlement data is not rendered as an arbitrary snapshot. Usage remains explicitly unavailable because no authoritative customer usage contract exists.

Repository-backed delivery is not available. Consequently the connection center displays an unavailable state and neither requests nor invents subscription links, configurations, tokens, or QR images. Provider writes remain disabled.

Billable service actions are visible for discoverability but disabled. The API rejects their creation until an authoritative, expiring quote flow exists; browser-selected amounts are not accepted as prices. Non-billable operation integration is intentionally deferred until the customer operation boundary also uses the unified authenticated-session dependency.

## Operations

No migration or new dependency is introduced. Deploy the API and customer web application together, then smoke-test `/services` and an owned `/services/{public-reference}` on a test account. Existing service list responses remain backward-compatible.

Roll out behind the existing authenticated customer surface. Monitor API 401/404/5xx rates and frontend section retry rates. Roll back by reverting this change; there is no data rollback. Provider integration, authoritative usage, repository-backed delivery, QR issuance, operation quotes, and payment orchestration are intentionally deferred.

## UI-4.1 deployed-list polish

Android Telegram captures showed that the fixed navigation could cover the empty card, the empty page repeated its storefront action, and the controls dominated short viewports. The services page now reserves the measured 66px navigation content height plus the Telegram safe-bottom inset and 20px breathing room, also using scroll padding; that reservation is removed when desktop navigation is hidden.

The zero-service header now delegates purchase to the empty state's single primary action. Populated lists retain a compact purchase action. Count, localized refresh time, and in-place refresh form one stable status row; refresh requests are deduplicated. Search, native RTL sorting, and the five centralized customer lifecycle groups use a compact responsive toolbar. Unknown/degraded states remain available through «همه» without exposing internal codes.

The Playwright matrix covers 320–1440px Android, iPhone, Telegram Desktop, and wide desktop empty states plus active and mixed mocked lists. It checks navigation clearance, horizontal overflow, action cardinality, filter completeness, in-place refresh, and customer-safe output. Screenshots are written to `test-results/screenshots/services-ui41` for manual review of density, proportions, filter scrolling, and platform appearance.

This is presentation-only and introduces no API, ownership, authentication, provider, or data changes. Roll out with the customer web artifact and verify `/services` at narrow Telegram sizes. Roll back by reverting UI-4.1; there is no migration or data rollback.
