# Provider contract dossier

Extraction date: 2026-07-18. Official tagged source is authoritative; community wrappers, old wiki pages and different forks are non-authoritative.

## Compatibility target

This dossier is paired with the path/tag shown in its directory name and adapter constants. Release metadata was re-verified from official GitHub releases on 2026-07-18.

## Milestone 6-A2A write-contract layer

The adapter defines provider-specific upstream DTO names, endpoint identifiers, method, authentication, content type, success/error conditions, atomicity, natural idempotency, side effects, read-after-write endpoint class, compensation strategy, sensitive fields and capability evidence in `panel_adapters.write_contracts`. Production execution is disabled until a later milestone.

## Common safety semantics

- Traffic is normalized as integer bytes; unlimited and zero are distinct.
- Expiry is normalized as UTC; no-expiry and expired are distinct.
- Nullable, missing and empty fields are handled explicitly.
- Raw request payloads, UUIDs, passwords, cookies, API keys and full endpoint URLs are not exposed in dry-run plans, logs, API responses or the DOM.
- HTTP 200 alone is never success; authoritative read-after-write postconditions are required.
- Ambiguous timeouts require read-before-retry and may move operations to uncertain/manual review.

## Provider-specific evidence summary

### Sanaei 3X-UI v3.5.0

- Repository: `https://github.com/MHSanaei/3x-ui`; tag `v3.5.0`; release commit `4e928a1`.
- Route evidence: `/panel/api/clients` and `/panel/api/inbounds` controller/service/DTO source in the official v3.5.0 tag.
- Authentication: panel session cookie; no raw credentials in plans.
- Identifier semantics: global client identity is distinct from inbound attachment; multi-inbound relationships are preserved where verified.
- Supported contract-only write operations: create, update, enable, disable, delete, reset traffic, clear client IPs, attach inbound and detach inbound.
- MTProto/WireGuard create/update remains unsupported unless exact credential DTOs are fully verified.

### Alireza X-UI v1.11.3

- Repository: `https://github.com/alireza0/x-ui`; tag `v1.11.3`; release commit `419fce7`.
- Route evidence: `/xui/API/inbounds/addClient/`, `/xui/API/inbounds/updateClient/:clientId`, `/xui/API/inbounds/:id/delClient/:clientId`, `/xui/API/inbounds/:id/resetClientTraffic/:email` in official route/controller source.
- Authentication: session cookie; CSRF is modeled as required when present in tagged source.
- Identifier semantics: VLESS/VMess use client ID; Trojan uses password; Shadowsocks preserves official identifier/email semantics. Email is not a universal remote identity.
- Supported contract-only write operations: create, update/full replacement, enable, disable, delete and reset traffic.
- Unsupported: Sanaei `/panel/api` paths, unverified multi-inbound assignment, unverified clear-IP.
