# UI-4.2 premium services center

## Scope and diagnosis

The former Android presentation prioritized record-like text, repeated headings, oversized disabled actions, and tabs that could clip. UI-4.2 gives the public service name and translated lifecycle priority, adds compact time and traffic metrics, makes tabs horizontally reachable, and reserves bottom-navigation clearance.

## Customer API contract and security

Customer list responses use an explicit summary DTO and detail uses an explicit detail envelope. Entitlement output is allowlisted to product label, quota, duration, device limit, location, quality, and required attachment count. Integers reject booleans, negative values, and bounded abuse; visible strings are trimmed and length bounded. Snapshot, allocation, provider, credential, and arbitrary keys are never serialized. Admin DTOs remain unchanged.

There is no authoritative provider usage repository. `usage` is therefore nullable and remains `null` in production. The UI explicitly says unsynchronized usage is not zero. Provider writes, pricing, checkout, delivery credentials, and configuration generation remain out of scope.

## Metric behavior

Remaining percentage is `(expires_at - now) / (expires_at - starts_at)`, clamped to 0–100. Invalid/non-positive intervals are unavailable, expired services show zero, and missing expiry is presented as unlimited. Traffic uses binary units. A synchronized response can show used percentage; quota without usage uses a neutral dashed ring and never shows 0%.

SVG rings include textual labels and progress semantics only when a real percentage exists. Tabs use tab roles, focus relationships, keyboard navigation, 44px targets, auto-scroll, reduced-motion behavior, RTL-safe references, and visible copied feedback.

## QA, rollout, and rollback

Validate mocked active, provisioning, suspended, expired, synchronized and unsynchronized states at 320–1440px in light/dark themes. Confirm no horizontal overflow or bottom-nav intersection. Roll out API and customer web together because the customer DTO changes; admin APIs are compatible. Roll back both artifacts together. Provider usage integration is explicitly deferred until a trusted repository and synchronization contract exist. No database migration is required.
