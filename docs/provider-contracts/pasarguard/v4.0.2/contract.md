# PasarGuard panel provider contract dossier — v4.0.2

Extraction date: 2026-07-18. Authoritative target re-verified from the official GitHub release page: `PasarGuard/panel` tag `v4.0.2`, release commit `0b0ddaa`.

## Milestone 6-A2A correction

Milestone 6-A1 references to PasarGuard `v5.1.0`, generated OpenAPI, panel API-key authentication, and RBAC permission claims are invalidated for VPN-SALE. The v4.0.2 panel source is authoritative. Panel administrator credentials are distinct from PasarGuard node/node-bridge credentials; node REST/gRPC API keys are not administrator panel credentials.

## Source evidence

- Repository: `https://github.com/PasarGuard/panel`
- Tag: `v4.0.2`
- Release commit: `0b0ddaa`
- Route evidence: panel user, node, host/template and system/status route files in the tagged source.
- Authentication evidence: administrator session-auth source files in the tagged panel; no verified panel API-key or generated OpenAPI endpoint is claimed by this dossier.
- Contract digest: `sha256:pasarguard-v4.0.2-read-write-a2a-corrected-contract`

## Read contract

Read-only functionality remains limited to version/status detection plus verified inventory discovery for users/nodes/host/template metadata where the panel response is runtime-validated. Unknown or inaccessible fields remain `UNKNOWN` rather than inferred.

## Write-operation evidence and DTOs

| Operation | Endpoint identifier | Method | Request DTO | Response DTO | Support | Evidence |
|---|---:|---:|---|---|---|---|
| CreateRemoteIdentity | `pasarguard.users.create` | POST | `PasarGuardUserCreateRequest` | `PasarGuardUserEnvelope` | supported by contract only | ID-based user aggregate create route in v4.0.2 panel source |
| UpdateRemoteIdentity | `pasarguard.users.update` | PATCH | `PasarGuardUserUpdateRequest` | `PasarGuardUserEnvelope` | supported by contract only | ID-based user modification route |
| EnableRemoteIdentity | `pasarguard.users.enable` | PATCH | `PasarGuardUserStatusRequest` | `PasarGuardUserEnvelope` | supported by contract only | user status field update |
| DisableRemoteIdentity | `pasarguard.users.disable` | PATCH | `PasarGuardUserStatusRequest` | `PasarGuardUserEnvelope` | supported by contract only | user status field update |
| DeleteRemoteIdentity | `pasarguard.users.delete` | DELETE | `PasarGuardUserIdPath` | `PasarGuardDeleteEnvelope` | supported by contract only | ID-based user deletion route |
| ResetRemoteTraffic | `pasarguard.users.resetTraffic` | POST | `PasarGuardUserResetTrafficRequest` | `PasarGuardUserEnvelope` | supported by contract only | user traffic reset route |

All production execution is disabled in Milestone 6-A2A. Successful HTTP responses are insufficient without read-after-write verification.

## Semantics

- Identifier semantics: PasarGuard users are first-class panel aggregates; they are not X-UI inbound clients.
- Relationships: users may relate to protocols, hosts, templates, groups, nodes and core configuration as required by the panel. Commerce provisioning must not directly invoke node-bridge methods.
- Traffic units: bytes at VPN-SALE boundary; conversion must be explicit where panel DTOs differ.
- Expiry units: UTC instants at VPN-SALE boundary; conversion must preserve no-expiry versus expired.
- Nullable fields: missing, null, zero and unlimited values are distinct.
- Side effects: user mutations can trigger panel-managed node synchronization and eventual consistency; node synchronization is not invoked directly by commerce provisioning.
- Unsupported: host mutation, template mutation, HWID mutation, node-bridge operations, OpenAPI discovery, panel API-key auth, direct subscription identity revocation, multi-inbound X-UI-style attachment.

## Postconditions and compensation

Create verifies user existence, credential fingerprint where safely comparable, enabled state, limits, expiry and relationships. Update verifies only expected fields changed. Enable/disable preserve limits and traffic. Reset verifies provider counter semantics while shop lifetime accounting remains unchanged. Delete verifies absence via authoritative read and unrelated resources unchanged. Ambiguous timeouts require read-before-retry; failed or partial operations become uncertain/manual-review rather than blind retries.
