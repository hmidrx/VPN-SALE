# Milestone 4-A2B1 Plan — Administrator Payment Operations Console

## Route inventory
- `/management/payments` payment operations overview using backend aggregates only when available.
- `/management/payment-methods` cursor-paginated payment-method discovery.
- `/management/payment-methods/new` draft creation for non-sensitive policy and localization.
- `/management/payment-methods/[methodReference]` detail, policy edit surface, lifecycle review, health, audit and security links.
- `/management/payment-intents` cursor-paginated intent discovery.
- `/management/payment-intents/[paymentReference]` immutable intent inspection.
- `/management/payment-attempts/[attemptReference]` attempt and verification inspection.
- `/management/payment-settlements/[settlementReference]` immutable read-only settlement inspection.
- `/management/payment-webhooks` cursor-paginated sanitized webhook inbox.
- `/management/payment-webhooks/[webhookReference]` sanitized webhook detail and eligible retry confirmation.
- Controlled unauthorized, service-unavailable, generic payment error and not-found states are represented by shared payment shell components.

## Permissions
The UI uses backend permission codes without broadening them: `payment_methods.read`, `payment_methods.manage`, `payments.read`, `payment_webhooks.read`, `payment_webhooks.retry`, `audit.read`, `security_events.read`, and `ledger.read`. Navigation is permission-aware in structure, direct route access remains backend-authoritative, and stale frontend permissions degrade to controlled 403 states.

## Payment-method lifecycle
Draft creation never activates a method implicitly. Lifecycle commands are distinct: activate, pause, enter maintenance, leave maintenance, retire, and archive only if the backend exposes support. Each review reloads current state, presents current and resulting status, requires confirmation/reason when required, sends an optimistic version, prevents duplicate submission, and refreshes method and health after backend success. Activation is blocked by backend adapter registration, credential state and fake-adapter production checks.

## Payment-state terminology
Payment intents keep immutable amount, purpose and customer context. Attempts and verification results are immutable after success. Settlements are immutable journals and read-only in this milestone. Unknown provider states are displayed as unknown/pending rather than coerced to success or failure. Reconciliation-required and refund summaries are read-only warnings only when supplied by the backend.

## Webhook processing
The webhook inbox displays webhook reference, method/provider, adapter version, received/processed timestamps, signature verification state, processing state, retry state, dead-letter state, safe failure category, linked payment reference and correlation ID. Detail pages render allowlisted sanitized metadata only. Invalid-signature or rejected webhooks cannot be retried as trusted events. Eligible retry uses the real backend retry command, honors `Retry-After`, avoids optimistic success, and explains duplicate settlement protection.

## Credential boundaries
Gateway credentials, merchant secrets, webhook secrets, unredacted signatures, Authorization/Cookie headers, raw provider payloads, idempotency values and request fingerprints are never rendered, logged or stored. The UI displays only backend-supplied credential states such as configured, missing, invalid reference and rotation required.

## Security controls
Access tokens remain memory-only through the existing auth client. API requests use `cache: 'no-store'`, CSRF headers for mutations, refresh single-flight, correlation-ID-safe error mapping, bounded URL filters and runtime response validation. Secret-like metadata keys are redacted defensively even if a backend accidentally includes them.

## Storage policy
No auth, payment-method, intent, attempt, verification, settlement, webhook, credential, retry form, customer profile or full API response data is stored in localStorage, sessionStorage, IndexedDB or service-worker cache. Safe non-sensitive filters may appear in URLs.

## Non-goals
This milestone does not implement customer payment UI, refunds administration, reconciliation repair, real gateways, merchant credential setup, card-to-card accounts, receipt uploads, bank-card collection, cryptocurrency, mixed payments, arbitrary mark paid controls, force success controls, settlement creation, direct wallet credit, invoice-paid mutation, VPN providers, Sanaei, Alireza X-UI, PasarGuard, provisioning, subscriptions, reseller settlement, support/live chat or analytics dashboards.

## Acceptance criteria
1. Authorized administrators inspect and manage payment methods through real backend APIs.
2. Only non-sensitive method policy and localization are editable.
3. Credentials and secret references are not exposed.
4. Lifecycle actions use backend commands and optimistic versions.
5. Fake adapters cannot activate in production.
6. Intents, attempts, verifications and settlements are inspectable.
7. Settlements remain immutable and read-only.
8. No mark paid, force success, settlement creation or refund controls exist.
9. Webhooks are safely inspectable without raw body or signature rendering.
10. Invalid-signature webhooks cannot be retried as trusted events.
11. Eligible retries use backend commands with duplicate-click and Retry-After handling.
12. Method health, adapter state and credential state are displayed safely.
13. Audit and Security Center links respect permissions.
14. Rial and derived toman are explicitly labelled.
15. Browser persistence is not used for auth, payment or webhook data.
16. Persian RTL, LTR technical references, accessible filters/tables/dialogs and reduced-motion behavior are preserved.
17. Behavioral and E2E fixtures use deterministic fake adapter test configuration only.
18. Existing customer payment, wallet, order and bot flows remain in scope only as regression checks.

## Backend compatibility notes
The admin-web clients are prepared for the merged 4-A1 backend route family under `/api/v1/admin/payments`. Compatibility additions, if needed later, must remain minimal typed Pydantic schemas with authorization enforcement and no raw credential or arbitrary success endpoints.
