# Phase 1A.1.1 UI hardening and visual QA

## Baseline audit

The work starts from merge `db692416457bef53bfe8731c07ce3f6fb522bacb`. Phase 1A.1 had a useful visual vocabulary, but its implementation was not yet a safe identity foundation:

- more than forty primitives shared one compressed client-oriented module;
- `IconButton` did not enforce a name and disabled links retained an `href`;
- `Field` used one description ID, discarded caller descriptions, and combined hint/error output;
- every dialog shared the same title ID; modal cancellation and focus restoration were implicit; drawer and bottom sheet were aliases;
- menu, tooltip, pagination, table row keys, command search IDs, and live regions had incomplete or misleading contracts;
- Telegram versions compared only two segments, storage was fire-and-forget and key-only filtered, and event/button ownership was not behaviorally tested;
- adapter and design-system tests inspected source text rather than rendered/native behavior;
- the identity gallery contained a phone-number registration concept and repeated generic disabled cards;
- there was no deterministic browser screenshot job or review artifact.

## Resulting contracts

UI components are grouped by actions, forms, feedback, navigation, overlays, data, shell, and internal utilities. Public exports remain available from `@vpnsale/ui`. Native dialogs provide unique labels, Escape cancellation, focus entry/return, and top-layer background blocking. Drawer and bottom sheet have distinct logical-placement and safe-area presentation. Tabs deliberately remain labelled navigation rather than claiming incomplete ARIA tab behavior; dropdown remains an honest disclosure rather than a false menu.

The Telegram package is split into native environment access, types, versions, events, buttons, storage, theme synchronization, and its public adapter. Storage returns typed Promise results and rejects identity, authorization, session, password, role, account and token material from keys or values. Raw `initData` is exposed only as an opaque server-verification input; no `initDataUnsafe` identity API exists.

## Visual QA

`npm run test:e2e` builds the customer preview with the explicit preview flag and starts it locally. Chromium captures fixed-size, reduced-motion screenshots into `test-results/screenshots`; CI uploads these and the HTML report as `phase-1a1-visual-qa`. No pixel baseline is enforced before human review.

Preview compositions are presentation-only. They have no form submit behavior, identity state, cookies, or authentication requests. In production the route remains unavailable unless `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true` is deliberately set.

## Security, rollback, and local use

No migrations, provider calls, commerce operations, credentials, or identity writes are introduced. Rollback is a normal code revert; there is no data rollback. Run `NEXT_PUBLIC_IDENTITY_UI_PREVIEW=true npm run build -w @vpnsale/customer-web`, then start that workspace to inspect `/ui-preview`. Install Chromium once with `npx playwright install chromium` before local visual QA.
