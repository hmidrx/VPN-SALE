# Provider contract dossier

Extraction date: 2026-07-18, re-verified for BOT-2A.1 and BOT-2B.1 on 2026-08-15. Official tagged source is authoritative; community wrappers, old wiki pages and different forks are non-authoritative.

## Compatibility target

Repository: `https://github.com/MHSanaei/3x-ui`

Tag: `v3.5.0`

Exact release commit: `4e928a1ce0945a6e956aa63365034ec24d2b1387`

The release commit and exact routes/DTOs below were re-verified directly against the official tagged source before enabling production CREATE or activation execution.

## BOT-2A.1 / BOT-2B.1 write-contract layer

The adapter defines provider-specific upstream DTO names, endpoint identifiers, method, authentication, content type, success/error conditions, atomicity, natural idempotency, side effects, read-after-write endpoint class, compensation strategy, sensitive fields and capability evidence in `panel_adapters.write_contracts`.

BOT-2A.1 implements the exact certified Sanaei CREATE operation. BOT-2B.1 adds only the exact global-client UPDATE needed to activate an already-created identity and the authenticated read-only client-link route needed to prepare customer delivery. Other provider mutations remain fail-closed until separately reviewed/certified.

## Common safety semantics

- Traffic is normalized as integer bytes; unlimited and zero are distinct.
- Expiry is normalized as UTC; no-expiry and expired are distinct.
- Nullable, missing and empty fields are handled explicitly.
- Raw request payloads, UUIDs, passwords, cookies, API keys and full endpoint URLs are not exposed in dry-run plans, logs, API responses or the DOM.
- HTTP 200 alone is never success; the response envelope and authoritative read-after-write postconditions are required.
- Ambiguous timeouts require read-before-retry and may move operations to uncertain/manual review.
- CREATE is not treated as naturally idempotent. A deterministic identity plus authoritative reconciliation is required before any retry or compensation.
- Activation never starts the paid entitlement clock until provider state and provider-generated customer delivery links have both been verified and the encrypted delivery record can be committed atomically with local ACTIVE state.

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

BOT-2A.1 deliberately creates the provider identity disabled and without a paid expiry clock:

```json
{
  "client": {
    "id": "<persisted deterministic UUID>",
    "email": "<provider-safe deterministic label>",
    "enable": false,
    "totalGB": "<purchased traffic bytes>",
    "expiryTime": 0,
    "limitIp": "<purchased device limit>",
    "tgId": 0,
    "subId": "<stable non-secret idempotency-derived value>",
    "comment": "<safe remark>"
  },
  "inboundIds": [1]
}
```

The production executor requires an explicit configured numeric inbound ID and never borrows Alireza `/addClient` route semantics.

Authentication uses the panel session cookie. Raw credentials/cookies are never included in logs, dry-run plans, provider results or customer responses.

### Sanaei v3.5.0 activation UPDATE

The official tagged controller registers:

- `GET /panel/api/clients/get/:email`
- `POST /panel/api/clients/update/:email`
- `GET /panel/api/clients/links/:email`

For `POST /panel/api/clients/update/:email`, `internal/web/controller/client.go` binds the JSON body directly to `model.Client` and passes it to `ClientService.UpdateByEmail`. BOT-2B.1 therefore first reads the authoritative global client record, preserves provider-owned fields, and changes only the activation fields required by the purchased entitlement:

- deterministic `id` remains unchanged;
- deterministic provider-safe `email` remains unchanged;
- `enable` becomes `true`;
- `totalGB` remains the purchased byte quota;
- `limitIp` remains the purchased device limit;
- `expiryTime` becomes the activation instant plus the full purchased duration.

The activation executor requires a non-empty expected remote snapshot and the same exact provider version/digest certification as CREATE. It reads before mutation, verifies all desired activation fields after mutation, and treats response loss as ambiguous rather than as permission to blindly replay an update.

A retry after an ambiguous/crash window computes a fresh activation instant. If the remote activation already happened but local delivery did not commit, reconciliation either confirms the exact new desired state or updates expiry to the new activation instant plus the full purchased duration. This prevents downtime/crash time from consuming the customer's purchased duration before usable delivery.

### Sanaei v3.5.0 provider-generated delivery links

The tagged controller implements `GET /panel/api/clients/links/:email` through `InboundService.GetAllClientLinks`. The tagged service implementation returns `[]string` generated for all inbounds assigned to that global client.

BOT-2B.1 accepts those links only after authoritative activation verification. It bounds link count and total size, requires the expected purchased protocol scheme, and encrypts the complete URI list before any durable database write. Plain provider connection URIs are not stored in the database.

### Sanaei read/reconciliation evidence

- Version detection: `/panel/api/server/status`.
- Authoritative inventory: `/panel/api/inbounds/list` plus the certified client/inbound parser.
- Authoritative activation record: `/panel/api/clients/get/:email`.
- Provider-generated customer links: `/panel/api/clients/links/:email`.
- CREATE reconciliation matches the persisted remote client identity first and the deterministic provider-safe label as a secondary recovery key.
- A lost CREATE response is never blindly replayed: inventory is read before another CREATE is attempted.
- A lost activation response is reconciled through the exact global-client read before another state-changing update is accepted as necessary.

### Alireza X-UI v1.11.3

- Repository: `https://github.com/alireza0/x-ui`; tag `v1.11.3`; release commit `419fce7`.
- Route family includes `/xui/API/inbounds/addClient/`, `/xui/API/inbounds/updateClient/:clientId`, `/xui/API/inbounds/:id/delClient/:clientId`, `/xui/API/inbounds/:id/resetClientTraffic/:email` in its own official route/controller source.
- These routes are not reused for Sanaei.
- Authentication: session cookie; CSRF is modeled as required when present in tagged source.
- Identifier semantics: VLESS/VMess use client ID; Trojan uses password; Shadowsocks preserves official identifier/email semantics. Email is not a universal remote identity.
