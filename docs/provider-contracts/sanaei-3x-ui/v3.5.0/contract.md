# Provider contract dossier

Extraction date: 2026-07-18, re-verified for BOT-2A.1 on 2026-08-15. Official tagged source is authoritative; community wrappers, old wiki pages and different forks are non-authoritative.

## Compatibility target

Repository: `https://github.com/MHSanaei/3x-ui`

Tag: `v3.5.0`

Exact release commit: `4e928a1ce0945a6e956aa63365034ec24d2b1387`

The release commit and exact route/DTO below were re-verified directly against the official tagged source before enabling any production CREATE implementation.

## Milestone 6-A2A / BOT-2A.1 write-contract layer

The adapter defines provider-specific upstream DTO names, endpoint identifiers, method, authentication, content type, success/error conditions, atomicity, natural idempotency, side effects, read-after-write endpoint class, compensation strategy, sensitive fields and capability evidence in `panel_adapters.write_contracts`.

BOT-2A.1 implements only the exact certified Sanaei CREATE operation. Other provider mutations remain fail-closed until separately reviewed/certified.

## Common safety semantics

- Traffic is normalized as integer bytes; unlimited and zero are distinct.
- Expiry is normalized as UTC; no-expiry and expired are distinct.
- Nullable, missing and empty fields are handled explicitly.
- Raw request payloads, UUIDs, passwords, cookies, API keys and full endpoint URLs are not exposed in dry-run plans, logs, API responses or the DOM.
- HTTP 200 alone is never success; the response envelope and authoritative read-after-write postconditions are required.
- Ambiguous timeouts require read-before-retry and may move operations to uncertain/manual review.
- CREATE is not treated as naturally idempotent. A deterministic identity plus authoritative reconciliation is required before any retry or compensation.

## Provider-specific evidence summary

### Sanaei 3X-UI v3.5.0 CREATE

Official source evidence at `4e928a1ce0945a6e956aa63365034ec24d2b1387`:

- `internal/web/controller/api.go` mounts the client controller under `/panel/api/clients`.
- `internal/web/controller/client.go` registers `POST /add`, therefore the exact CREATE route is `POST /panel/api/clients/add`.
- The controller binds a JSON request to `service.ClientCreatePayload`.
- `internal/web/service/client.go` defines `ClientCreatePayload` as a `client` object plus `inboundIds []int`.
- `internal/web/service/client_crud.go` requires a non-empty client email and at least one inbound, preserves/reuses an existing identity only when the global identity semantics match, and attaches the global client to each requested inbound.
- VLESS/VMess client `id` is the remote credential identity; BOT-2A.1 supplies the persisted deterministic UUID instead of allowing a retry to mint another UUID.
- The JSON response uses the standard `success` envelope; HTTP 200 by itself is not authoritative success.

Certified CREATE request shape:

```json
{
  "client": {
    "id": "<persisted deterministic UUID>",
    "email": "<provider-safe deterministic label>",
    "enable": true,
    "totalGB": 0,
    "expiryTime": 0,
    "limitIp": 0,
    "tgId": 0,
    "subId": "<stable non-secret idempotency-derived value>",
    "comment": "<safe remark>"
  },
  "inboundIds": [1]
}
```

The production executor requires an explicit configured numeric inbound ID and never borrows Alireza `/addClient` route semantics.

Authentication uses the panel session cookie. Raw credentials/cookies are never included in logs, dry-run plans, provider results or customer responses.

### Sanaei read/reconciliation evidence

- Version detection: `/panel/api/server/status`.
- Authoritative inventory: `/panel/api/inbounds/list` plus the certified client/inbound parser.
- Reconciliation matches the persisted remote client identity first and the deterministic provider-safe label as a secondary recovery key.
- A lost CREATE response is never blindly replayed: inventory is read before another CREATE is attempted.

### Alireza X-UI v1.11.3

- Repository: `https://github.com/alireza0/x-ui`; tag `v1.11.3`; release commit `419fce7`.
- Route family includes `/xui/API/inbounds/addClient/`, `/xui/API/inbounds/updateClient/:clientId`, `/xui/API/inbounds/:id/delClient/:clientId`, `/xui/API/inbounds/:id/resetClientTraffic/:email` in its own official route/controller source.
- These routes are not reused for Sanaei.
- Authentication: session cookie; CSRF is modeled as required when present in tagged source.
- Identifier semantics: VLESS/VMess use client ID; Trojan uses password; Shadowsocks preserves official identifier/email semantics. Email is not a universal remote identity.
