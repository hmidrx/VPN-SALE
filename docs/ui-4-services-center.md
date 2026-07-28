# UI-4.3 premium services center

## Scope and real Android diagnosis

UI-4.3 is the final customer-facing presentation pass before wallet and payment work. Real Android Telegram Mini App review of UI-4.2 found a tall sticky detail header that could cover dashboard content, a final tab that could be clipped, repeated service references and overview facts, an overly bright segmented traffic ring, an incomplete information grid, oversized action areas, and insufficiently deliberate bottom-navigation clearance.

This change remains frontend-only. It does not alter service ownership, authentication, DTOs, pricing authority, provider integration, delivery, wallet, checkout, catalog, or database state. Usage remains `null` without an authoritative source, delivery remains unavailable without repository-backed delivery, billable actions remain disabled without authoritative pricing, and provider writes remain disabled.

## Before and after

### Service list

Before, each card repeated a lifecycle description and used a tall metadata stack. After, the translated status, short copyable reference, two compact metrics, four entitlement cells, and light 44px management action form one concise card. The final action has a bottom-navigation bounding-box assertion.

### Service overview

Before, the overview repeated the reference in a full-width control and an information row, repeated time facts around the ring, and left a half-row empty. After, it contains one summary, one shortened copy control, two equally sized metrics, exactly six real information cells, and at most three compact recommended actions. Activation and expiry occur once in the information grid; the exact expiry stays outside the ring.

## Interaction and accessibility

- The detail header is compact and in normal flow. Its refresh icon has a 44px target, disables duplicate requests, retains loaded content, and reports bounded success through `aria-live` without document navigation.
- Only the five-tab bar is sticky on mobile. Its solid canvas treatment, border, shadow, z-index, inline scroll padding, hidden scrollbar, and centered selection prevent dashboard bleed-through and make both edge tabs reachable.
- Tabs expose tablist/tab/panel relationships, roving `tabindex`, selected state, Left/Right, Home, and End keyboard controls. Deterministic 320px and 360px tests select both edge tabs and assert their complete bounding boxes.
- The only overview reference is shortened visually, LTR-isolated, copied in full, and reports «کپی شد» without logging clipboard data.
- Real percentages alone receive progressbar semantics. Unsynchronized traffic has no `aria-valuenow`, does not display 0%, uses a quiet neutral dash treatment and sync icon, and announces the total quota in its accessible description.
- Focus styles remain inherited from the shared UI, all interactive controls are at least 44px, and reduced-motion mode removes refresh rotation and smooth movement.

## Metrics and information

The time and traffic rings now share dimensions, stroke, spacing, center hierarchy, and minimum height. At 320px they intentionally stack; from 360px they remain paired. Expired time reaches a clear zero, missing expiry uses infinity, and invalid intervals remain neutral. Synchronized traffic uses one continuous used-percentage ring and presents used, remaining, total, percentage, last synchronization, and an optional stale badge. Missing quota remains explicitly unavailable.

The overview grid contains activation date, expiry date, location, quality, device count with a localized «دستگاه» unit, and connection readiness. Missing customer-safe values use «ثبت نشده». No internal code, provider metadata, configuration, credential, link, token, flag, or fabricated event is rendered.

## Compact states and management

Connection, usage, and activity use embedded compact states rather than full-page placeholders. No QR code or subscription link is invented. Recommended actions contain only eligible maintenance actions (up to two) plus support; disabled actions are not used as filler. The management tab groups purchase/renewal, connection/maintenance, and service status. One group banner explains unavailable financial authority instead of repeating the explanation on every operation.

## Responsive and visual QA

Deterministic Playwright coverage exercises 320×700, 360×800, 390×844, 393×852, 430×932, 768×1024, and 1440×900 layouts, including dark/light Android, iPhone, Telegram Desktop, empty and multiple-service lists, unsynchronized quota, synchronized usage, connection unavailable, management disabled, and activity empty states. It asserts no horizontal page overflow, edge-tab visibility, reference deduplication, quota wording, complete entitlement cells, device units, absent 0%, and bottom-navigation separation for the final list/detail actions.

Manual review of generated screenshots confirmed the restrained dark canvas, balanced metric pair, readable neutral unavailable state, compact actions, complete two-column information grid, and mobile/desktop containment. The test mocks intentionally contain no provider metadata, delivery token, configuration, fake activity, or `test_seed` field. Screenshot artifacts are CI outputs and are not committed.

## Security, rollout, and rollback

There are no security-authority, persistence, API contract, or dependency changes. Clipboard content is never logged, existing content is retained while refresh runs, and no operation submission or provider write is introduced.

Roll out the customer-web artifact normally after all six CI jobs pass. No migration, cache conversion, coordinated backend rollout, or customer data change is required. Rollback is replacement of the customer-web artifact with UI-4.2; because contracts and persisted state are unchanged, rollback is immediate and does not require data repair.

## Local verification

Install with `npm ci`, then run the repository lint, typecheck, unit, build, Playwright, security, Python, and Compose validation commands documented in `AGENTS.md`. For screenshot review, run `npm run test:e2e` and inspect `test-results/screenshots/services-ui41/` at native resolution.
