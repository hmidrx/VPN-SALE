# UI-4: customer services center

## Scope and safety

The former `/services` placeholder is replaced by a mobile-first list and a single detail route with overview, connection, usage, management, and activity sections. Customer-facing lifecycle labels are centralized and unknown values render as «در حال بررسی».

Service reads derive customer ownership from the authenticated customer session and return `404` for unowned public references. Required verified attachment totals are counted from service attachments; attachment and provider identifiers never enter the response. Entitlement data is not rendered as an arbitrary snapshot. Usage remains explicitly unavailable because no authoritative customer usage contract exists.

Repository-backed delivery is not available. Consequently the connection center displays an unavailable state and neither requests nor invents subscription links, configurations, tokens, or QR images. Provider writes remain disabled.

Billable service actions are visible for discoverability but disabled. The API rejects their creation until an authoritative, expiring quote flow exists; browser-selected amounts are not accepted as prices. Non-billable operation integration is intentionally deferred until the customer operation boundary also uses the unified authenticated-session dependency.

## Operations

No migration or new dependency is introduced. Deploy the API and customer web application together, then smoke-test `/services` and an owned `/services/{public-reference}` on a test account. Existing service list responses remain backward-compatible.

Roll out behind the existing authenticated customer surface. Monitor API 401/404/5xx rates and frontend section retry rates. Roll back by reverting this change; there is no data rollback. Provider integration, authoritative usage, repository-backed delivery, QR issuance, operation quotes, and payment orchestration are intentionally deferred.
