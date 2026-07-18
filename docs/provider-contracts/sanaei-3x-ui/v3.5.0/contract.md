# Certified read-only provider contract

Status: CONTRACT_VERIFIED from official source/release-page research on 2026-07-18; LIVE_UNVERIFIED until a real staging panel completes live certification.

## Evidence fields

- Upstream repository: see table below.
- Release tag: see table below.
- Full commit SHA: recorded in adapter constants; abbreviated release commit was verified on GitHub release pages.
- Authentication: read-only machine credential preferred where the panel exposes it; session-cookie fallback only when that panel contract requires session login.
- Base paths: exact panel-family paths are adapter-specific and custom web base paths must be prepended by configuration.
- Contract digest: stable normalized digest is stored in adapter constants; live OpenAPI digest mismatch fails closed.
- Time/traffic: byte counters are bytes; X-UI epoch timestamps are treated as milliseconds only when the certified response field documents milliseconds, otherwise parsed defensively as seconds with explicit evidence.
- Nullable fields: client statistics, envelope objects, online state and optional host/template metadata are nullable/unsupported unless the certified endpoint exposes them.

## Endpoint inventory summary

| Provider | Release | Release date | Read authentication | Base paths | Read inventory |
|---|---:|---:|---|---|---|
| MHSanaei/3x-ui | v3.5.0 | 2026-07-12 | API Token preferred; panel session fallback | `/panel/api/inbounds`, `/panel/api/clients`, `/panel/api/server`, `/panel/api/nodes`, `/panel/api/openapi.json` | server status, nodes, inbounds, clients, traffic, online state |
| alireza0/x-ui | v1.11.3 | 2026-07-04 | session login cookie | `/xui/API/inbounds`, `/xui/API/outbounds`, `/xui/API/routing`, `/xui/API/server` | server status, inbounds, clients, outbounds/routing references where safe |
| PasarGuard/panel | v5.1.0 | 2026-07-14 | official API key/RBAC permissions | generated OpenAPI API routes for users, nodes, hosts/templates and system status | users, nodes, hosts, templates, core/inbound metadata, traffic, expiry/HWID where exposed |

## Unsupported or deferred

- Mutation endpoints are deliberately not called and map to `PROVIDER_OPERATION_NOT_ENABLED`.
- Unknown versions can run diagnostics only.
- Live verification requires an operator-owned staging panel with read-only credentials.
