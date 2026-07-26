# Phase 1A.1 — UI and Telegram foundation

## Audit and migration

The three web applications use the Next.js App Router. Customer routes share a large client-side `CustomerApp`, while admin pages and reseller pages have independently grown global CSS and repeated cards, badges, navigation, tables, and form controls. `packages/ui` previously exported only three raw colors, one radius, and direction constants; it had no React surface or semantic theme contract. Docker builds use the existing per-app Next standalone configuration, which remains unchanged.

Migration is intentionally incremental: the semantic stylesheet is loaded by each root layout, compatibility token aliases preserve current routes, and new work can adopt typed components without rewriting existing business views. Reseller capability navigation belongs in the customer shell by role; the current reseller application remains operational until a later redirect is explicitly planned.

## Visual contract

Dark obsidian canvas and restrained cyan primary, violet accent, and semantic success/warning/danger/info colors are expressed in OKLCH CSS variables. Raised surfaces use low-contrast borders and one soft shadow. Dark is the default; an explicit light fallback, Telegram variables, increased/forced contrast, stable viewport/safe-area variables, 44px controls, container-ready cards, and reduced-motion behavior are included. A bundled font asset should be added only after its license and exact artifact are reviewed; builds deliberately make no network font request and currently use a reproducible system Persian stack.

## Security and rollout

`/ui-preview` is a deterministic, no-network gallery. Production returns not-found unless `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true` is intentionally supplied at build time. Its identity forms never submit. The Telegram adapter exposes raw `initData` only for future server verification, never treats `initDataUnsafe` as identity, and rejects token/role/account-shaped storage keys. No database, authentication backend, payment, provider, admin, or reseller write is introduced.

Rollback consists of reverting this commit: no data or migration rollback is needed. Local preview: set `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true`, run `npm run build -w @vpnsale/customer-web`, then start that workspace and open `/ui-preview`.

## Bot presentation contract

Future bot menus may describe role-aware profile launches, menu-button and `startapp` deep links, inline button styles, custom emoji icon identifiers, copy-text actions, private-chat topics, rich messages, and ephemeral status messages. These are presentation contracts only. Every capability must be negotiated against the deployed Bot API and receiving client; fallback is a plain text message plus standard URL/callback button. Older clients receive neither rich formatting nor ephemeral management behavior. Admin actions remain unavailable.

## Deferred

A reviewed local Persian variable-font artifact, production identity routes, bot emission, authoritative Telegram validation, browser screenshot baselines, and reseller-domain redirect are deliberately deferred. Device/Secure/Cloud storage reads and biometric authorization flows require product threat-model review; this phase only reports capabilities and allows non-sensitive writes.
