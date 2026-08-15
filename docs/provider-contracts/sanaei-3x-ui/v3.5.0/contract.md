# Provider contract dossier

Extraction date: 2026-07-18, re-verified for BOT-2A.1 and BOT-2B on 2026-08-15. Official tagged source is authoritative; community wrappers, old wiki pages and different forks are non-authoritative.

## Compatibility target

Repository: `https://github.com/MHSanaei/3x-ui`

Tag: `v3.5.0`

Exact release commit: `4e928a1ce0945a6e956aa63365034ec24d2b1387`

The exact routes and DTO behavior below were re-verified directly against the official tagged source before enabling production CREATE or activation UPDATE execution.

## BOT-2A.1 / BOT-2B write-contract layer

The adapter defines provider-specific method, authentication, request/response semantics, success/error conditions, side effects, read-after-write requirements, compensation strategy and capability evidence in `panel_adapters.write_contracts` and `panel_adapters.write_execution`.

BOT-2A.1 certifies CREATE. BOT-2B additionally certifies the exact Sanaei full-client UPDATE used to activate the already-created identity. Other providers remain fail-closed until separately reviewed/certified.

## Common safety semantics

- Traffic is normalized as integer bytes; unlimited and zero are distinct.
- Expiry is normalized as UTC; no-expiry and expired are distinct.
- Nullable, missing and empty fields are handled explicitly.
- Raw request payloads, UUIDs, passwords, cookies, API keys and full endpoint URLs are not exposed in logs or customer-safe state.
- HTTP 200 alone is never success; the response envelope and authoritative read-after-write postconditions are required.
- Ambiguous timeouts require reconciliation before retry and may move operations to uncertain/manual review.
- CREATE is not treated as naturally idempotent. A deterministic identity plus authoritative reconciliation is required before any retry or compensation.
- Activation UPDATE is convergent: read current client, write the desired full state, then read it again. A lost response is success only if the authoritative read proves the exact desired state.

## Provider-specific evidence summary

### Sanaei 3X-UI v3.5.0 CREATE

Official source evidence at `4e928a1ce0945a6e956aa63365034ec24d2b1387`:

- `internal/web/controller/api.go` mounts the client controller under `/panel/api/clients`.
- `internal/web/controller/client.go` registers `POST /add`, therefore the exact CREATE route is `POST /panel/api/clients/add`.
- The controller binds a JSON request to `service.ClientCreatePayload`.
- `internal/web/service/client.go` defines `ClientCreatePayload` as a `client` object plus `inboundIds []int`.
- `internal/web/service/client_crud.go` requires a non-empty client email and at least one inbound and attaches the global client to each requested inbound.
- VLESS/VMess client `id` is the remote credential identity; BOT-2A.1 supplies the persisted deterministic UUID instead of allowing a retry to mint another UUID.
- The JSON response uses the standard `success` envelope; HTTP 200 by itself is not authoritative success.

Certified CREATE request shape:

```json
{
  "client": {
    "id": "<persisted deterministic UUID>",
    "email": "<provider-safe deterministic label>",
    "enable": false,
    "totalGB": 53687091200,
    "expiryTime": 0,
    "limitIp": 1,
    "tgId": 0,
    "subId": "<stable non-secret idempotency-derived value>",
    "comment": "<safe remark>"
  },
  "inboundIds": [1]
}
```

BOT-2A.1 deliberately creates the identity disabled and without purchased expiry. Paid duration does not start during provisioning.

### Sanaei 3X-UI v3.5.0 activation UPDATE

Official tagged source evidence:

- `internal/web/controller/client.go` registers `GET /get/:email`, `GET /links/:email` and `POST /update/:email` under `/panel/api/clients`.
- The exact update route is `POST /panel/api/clients/update/:email`.
- The update controller binds the JSON body directly to `model.Client` and calls `ClientService.UpdateByEmail`.
- `internal/web/service/client_crud.go` preserves the existing remote client ID when omitted and preserves protocol credential fields such as password/auth/secret when they are not supplied. BOT-2B nevertheless supplies the expected VLESS/VMess UUID explicitly and verifies it before and after mutation.
- Fields used for activation are `id`, `email`, `enable`, `totalGB`, `expiryTime`, `limitIp`, `tgId` and `comment`.
- BOT-2B does not change inbound assignment during activation; it verifies that the durable attachment still points to the originally selected allocation target.

Certified activation UPDATE shape:

```json
{
  "id": "<persisted deterministic UUID>",
  "email": "<existing provider-safe deterministic label>",
  "enable": true,
  "totalGB": 53687091200,
  "expiryTime": 1770000000000,
  "limitIp": 1,
  "tgId": 0,
  "comment": "customer service"
}
```

BOT-2B establishes one durable activation instant immediately before the first activation UPDATE, after delivery data has been staged securely. Local `starts_at`/`activated_at`, local `expires_at`, and provider `expiryTime` all derive from that same persisted clock. Retries reuse the same instant and expiry.

### Sanaei delivery-link evidence

- `GET /panel/api/clients/links/:email` is the exact tagged route used to obtain generated client links for the global client.
- The route returns the standard JSON success envelope; `obj` must be a bounded sequence of strings.
- Links are fetched before activation is declared deliverable, validated against allowed VPN URI schemes, encrypted at rest, and never stored in plaintext service/attachment state or logs.
- Customer delivery requires the local service to be ACTIVE, all required attachments verified, and an ACTIVE encrypted delivery revision.

### Sanaei read/reconciliation evidence

- Version detection: `/panel/api/server/status`.
- Authoritative inventory: `/panel/api/inbounds/list` plus the certified client/inbound parser.
- Exact activation read: `/panel/api/clients/get/:email`.
- Reconciliation checks the persisted remote identity and the desired enable/traffic/expiry/device-limit state before declaring UPDATE success.
- A lost CREATE or UPDATE response is never blindly replayed. The remote state is read first; only a proven desired state converges to success.

Authentication uses the panel session cookie. Raw credentials/cookies are never included in logs, provider results or customer responses.

### Alireza X-UI v1.11.3

- Repository: `https://github.com/alireza0/x-ui`; tag `v1.11.3`; release commit `419fce7`.
- Route family includes `/xui/API/inbounds/addClient/`, `/xui/API/inbounds/updateClient/:clientId`, `/xui/API/inbounds/:id/delClient/:clientId`, `/xui/API/inbounds/:id/resetClientTraffic/:email` in its own official route/controller source.
- These routes are not reused for Sanaei.
- Authentication: session cookie; CSRF is modeled as required when present in tagged source.
- Identifier semantics: VLESS/VMess use client ID; Trojan uses password; Shadowsocks preserves official identifier/email semantics. Email is not a universal remote identity.
