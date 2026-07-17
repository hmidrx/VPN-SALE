# ADR 0029: Reseller Core, Tenancy, Pricing and Financial Controls

## Status
Accepted

## Decision
Milestone 5-C models resellers as a separate aggregate linked to, but not merged with, customer identity. Customer, administrator and reseller tokens remain isolated. Reseller customer ownership is an allowlisted relationship and never provides impersonation.

Wholesale prices are evaluated on the backend from immutable product-version base prices, reseller-specific rules, price-book rules, tier/volume rules and finally minimum-price/margin floors. Every quote/order stores an immutable pricing explanation.

Reseller financial accounts reuse wallet/ledger invariants. Prepaid purchases reserve and capture reseller wallet funds. Controlled credit uses explicit limits, approval references and utilized receivable values; it is not a negative wallet assignment.

Custom remarks are presentation labels only. Templates use an explicit placeholder registry, bounded length, safe characters and immutable snapshots.

High-risk financial and ownership actions require separate approval; the creator cannot approve their own action. All mutations are idempotent, version-checked, audited and integrated with Security Center event categories.

## Consequences
- Historical price books and ownership changes never rewrite historical orders.
- Account-specific limits can only tighten effective tier limits.
- The reseller-web portal remains out of scope until Milestone 5-D, but typed API foundations exist now.
- VPN service provisioning and provider adapters remain out of scope.
