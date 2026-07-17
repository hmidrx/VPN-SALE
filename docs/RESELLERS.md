# Resellers

Reseller architecture covers onboarding, status, wallet/credit, wholesale pricing, product/routing overrides, commissions, settlements, owned customers, imports/exports, reports, API keys, branding, custom domains, notifications, and feature-flagged sub-resellers.

## Milestone 5-C reseller core

Milestone 5-C introduces reseller accounts, lifecycle, tier/limit policy, price books, managed customers, reseller-funded orders, safe remarks, prepaid wallet use and controlled credit foundations. All authoritative amounts remain integer rial and are evaluated by the backend. The full reseller-web portal and VPN provisioning remain out of scope.

## Milestone 5-D reseller-web portal

The reseller-web portal presents the Milestone 5-C reseller domain as a Persian RTL web experience. It covers reseller status, tier, quotas, wholesale catalog, authoritative pricing, quote review, reseller-funded checkout, prepaid wallet, controlled credit, managed customers, order history, safe remark templates, reseller-scoped branding, activity, and profile/security summaries.

Security boundaries remain backend-owned: pricing, wallet balances, credit utilization, customer ownership, idempotency, ledger effects, account status, and authorization are never trusted from the browser. The portal does not store tokens, CSRF values, Telegram initData, customer data, quote/order data, wallet/credit data, branding drafts, or idempotency keys in browser persistence. It does not display service credentials, QR codes, subscription URLs, servers, panels, traffic usage, provider health, or delivered-service claims before fulfillment integration.
