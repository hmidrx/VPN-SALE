# ADR 0012: Future Fulfillment and Provider Separation

## Status
Accepted for Milestone 2-A.

## Decision
Product versions store provider-neutral fulfillment capability codes only. They never store panel URLs, panel credentials, server IPs, provider-native inbound IDs or provider payloads. Future direction is Catalog/Product → Fulfillment requirements → Allocation engine → Provider contract → versioned provider adapters.

## Consequences
Sanaei, PasarGuard and future adapter changes do not alter catalog definitions or quote calculations.
