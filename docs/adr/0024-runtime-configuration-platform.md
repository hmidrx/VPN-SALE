# ADR 0024: Runtime configuration platform

## Decision
Use typed, versioned configuration namespaces, immutable release snapshots and short-lived preview sessions instead of an unrestricted settings table.

## Consequences
* Database configuration cannot override secrets or security-critical environment boundaries.
* Publishing creates a full runtime snapshot and cache invalidation event.
* Rollback creates a new release from historical immutable data.
* Themes are schema-based design tokens; raw CSS, arbitrary fonts and scripts are rejected.
* Feature flags use bounded typed rules and deterministic hashing, never arbitrary expressions.
* Templates use registered placeholders and destination escaping.
* Navigation and Telegram menus use safe destination/action registries only.
* Media assets require MIME/content validation, decoding, digesting and archive lifecycle.
* Runtime APIs expose evaluated booleans and public presentation data only.
