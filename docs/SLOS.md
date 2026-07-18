# VPN-SALE proposed SLOs

These are proposed operational targets until timed production evidence exists.

| Journey | Indicator | Objective | Window | Exclusions | Source | Alerts | Owner | Runbook |
|---|---|---:|---|---|---|---|---|---|
| Authenticated API | successful non-5xx requests | 99.5% proposed | 30d | maintenance | HTTP metrics | 2%/5% burn | Platform | docs/runbooks/api-degradation.md |
| Catalog/checkout | successful quote/session flow | 99.0% proposed | 30d | provider outage | app metrics | warning/critical | Commerce | docs/runbooks/api-degradation.md |
| Payment webhook | processed idempotently | 99.5% proposed | 30d | gateway outage | webhook metrics | failure surge | Payments | docs/runbooks/api-degradation.md |
| Provider operation | durable final or uncertain state | 99.0% proposed | 30d | panel outage | provider metrics | uncertain surge | Ops | docs/runbooks/provider-panel-outage.md |
| Usage freshness | sync age within policy | 99.0% proposed | 7d | panel outage | usage metrics | stale | Ops | docs/runbooks/provider-panel-outage.md |
| Admin access | successful authorized access | 99.5% proposed | 30d | IdP outage | auth metrics | error/latency | Security | docs/runbooks/api-degradation.md |
