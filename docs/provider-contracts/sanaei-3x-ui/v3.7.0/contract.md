# Sanaei/3x-ui v3.7.0 provider contract

Extraction date: 2026-08-25. This dossier is pinned to the official release tag and
does not certify `main`, another fork, or a merely similar route family.

## Compatibility identity

- Repository: <https://github.com/MHSanaei/3x-ui>
- Release: <https://github.com/MHSanaei/3x-ui/releases/tag/v3.7.0>
- Tag: `v3.7.0`
- Exact commit: `f727d04f6522bb94a8fb52e8352fdcafb51c11e1`
- Release date: 2026-08-24
- Local contract digest: `sha256:sanaei-3x-ui-v3.7.0-admin-client-contract`

The version-aware v3.7.0 client and executor are the production composition used by
provisioning, activation, renewal, traffic changes and usage synchronization. The old
v3.5.0 modules remain isolated legacy compatibility code; production workers do not
compose them. Every v3.7.0 mutation still requires an exact version/digest staging
certification and the global provider-write gate.

## Authentication and capability envelope

The tagged API gateway accepts either a logged-in panel session or
`Authorization: Bearer <token>`. The adapter prefers Bearer authentication for
automation because it is request-scoped and does not require login/session renewal.
Bearer authentication also bypasses the session CSRF check in the tagged gateway.

The release defines `admin`, `monitor` and `node-sync` token scopes and an optional
`expiresAt` value measured in Unix milliseconds. The complete contract in this folder
requires `admin`: the reduced `node-sync` allowlist includes selected mutations but not
the client readback/link routes needed to verify and deliver the result, while `monitor`
is read-only status/metrics access. A token's plaintext is shown only at creation and is
stored hashed by the panel; the platform must likewise treat the supplied token as a
write-only secret.

Official evidence:

- [API gateway and scoped route enforcement](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/controller/api.go)
- [API token model/service and expiry handling](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/service/panel/api_token.go)
- [CSRF behavior](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/session/csrf.go)
- [Security middleware](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/middleware/security.go)

The local capability envelope records Bearer first, session second, required Bearer
scope `admin`, exact supported operations, byte/millisecond units, and
`writes_enabled_by_default=false`. It is metadata, not authorization to mutate a panel.

Cookie fallback follows the tagged browser-session protocol rather than assuming that
a password is an API credential:

1. `GET {basePath}/csrf-token` on a stateful, cookie-preserving transport;
2. require the literal-success envelope and retain its opaque `obj` token;
3. `POST {basePath}/login` as JSON with `username`, `password` and `twoFactorCode`, plus
   `X-CSRF-Token: <token>`;
4. retain the session cookie set by the panel and send the same CSRF header on every
   later unsafe cookie-authenticated request.

The adapter implements this sequence in `authenticate_session`. It sends
`X-Requested-With: XMLHttpRequest` on cookie-authenticated management calls so an
expired or missing session produces 401 instead of the browser-oriented 404 response.
It never automatically replays a mutation after an authentication or transport
failure. Callers that inject an already-authenticated cookie transport must also inject
its matching CSRF token; cookie mutations fail closed before transport otherwise.

## Base path

The management API is mounted below the configured web base path. Every route below is
therefore requested as:

```text
{normalized-base-path}/panel/api/clients/...
```

An empty path and `/` normalize to no prefix; `tenant/panel/` normalizes to
`/tenant/panel`. Origins, query strings, fragments, backslashes, control characters and
decoded dot/traversal segments are rejected. Email and subscription identifiers are
percent-encoded as individual path segments.

Official mount evidence:

- [Web router and configured base path](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/web.go)
- [Panel API controller mount](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/controller/api.go)

## Exact multi-inbound and client subset

The tagged inbound controller exposes the lightweight multi-inbound picker:

| Operation | Method and route | Verified result |
| --- | --- | --- |
| Inbound picker | `GET /panel/api/inbounds/options` | success-envelope `obj` is an array with validated ID, label, tag, protocol, port, enable, node and TLS-flow facts |

The tagged client controller registers these routes under `/panel/api/clients`:

| Operation | Method and route | Verified body/result |
| --- | --- | --- |
| Create | `POST /add` | JSON `{"client": {...}, "inboundIds": [int, ...]}` |
| Readback | `GET /get/:email` | success-envelope `obj` contains `client`, `inboundIds`, `externalLinks`, `usedTraffic` and any tagged optional metadata |
| Update | `POST /update/:email?inboundIds=...` | canonical client JSON; readback verifies mutable limit/status fields and requested memberships |
| Delete | `POST /del/:email?keepTraffic=1` | empty JSON body; no automatic retry after an ambiguous result |
| Attach | `POST /:email/attach` | JSON `{"inboundIds": [int, ...]}` |
| Detach | `POST /:email/detach` | JSON `{"inboundIds": [int, ...]}` |
| Reset traffic | `POST /resetTraffic/:email` | empty JSON body |
| Clear client IPs | `POST /clearIps/:email` | empty JSON body |
| Direct links | `GET /links/:email` | success-envelope `obj` is an array of individual configuration strings |
| Sub-ID links | `GET /subLinks/:subId` | success-envelope `obj` is an array of individual configuration strings |

Official evidence:

- [Client controller routes, DTO binding and response construction](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/controller/client.go)
- [Inbound picker controller](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/controller/inbound.go)
- [Global-client create/update service DTOs](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/service/client.go)
- [Client CRUD and inbound relationship rules](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/internal/web/service/client_crud.go)
- [Generated client API reference](https://github.com/MHSanaei/3x-ui/blob/v3.7.0/docs/content/docs/en/reference/api/clients.mdx)

Create requires at least one numeric inbound ID. `totalGB` is an integer byte count,
despite its historical name. `expiryTime` is an integer Unix timestamp in milliseconds;
zero retains the panel's no-expiry convention. The adapter supplies an exact aware
datetime-to-millisecond helper and never converts these values to decimal gigabytes or
seconds.

The create/update response does not promise the canonical record. Successful create,
update, attach and detach calls are therefore followed by `GET /get/:email`; the client
verifies identity, requested relationships and mutable fields. A missing or mismatched
readback is not success. Delete/reset/clear operations are never blindly retried.

`GET /subLinks/:subId` is a management helper returning a JSON array of generated
individual links. It is not the public native subscription URL. The platform's own
revocable custom-origin subscription remains a separate delivery boundary. Provider
links contain credentials and must never be logged, persisted in diagnostics, or placed
in exception text.

Picker responses reject malformed or duplicate inbound IDs. Direct-link and sub-ID-link
responses must be arrays of non-empty, single-line strings. The adapter deliberately
does not restrict their schemes: the tagged panel supports several protocol URL formats,
and the application's secure delivery layer decides which representation to expose.

## Response and retry rules

Tagged controller helpers use the JSON envelope `success`, `msg`, `obj`; business errors
can arrive with HTTP 200. The client consequently requires both a 2xx response and the
literal boolean `success: true`, then validates the operation-specific `obj` shape. It
maps 401, 403, 408/504, 429 and other 5xx responses to sanitized provider errors and
never exposes upstream `msg`.

The adapter does not retry mutations. The injected transport owns bounded timeouts,
response-size limits, TLS verification/pinning, and safe retry policy. Callers must
read/reconcile before retrying an ambiguous add/update/attach/detach. Multi-panel scheduling
must isolate health/circuit state per panel so one failing endpoint cannot poison or
redirect another panel's request.

## Fixture policy

Files under `fixtures/` are hand-authored, fully synthetic contract examples. They are
not captures from a live panel. Identifiers use reserved example values and link values
use a deliberately nonfunctional scheme so they cannot be imported as working customer
configuration.
