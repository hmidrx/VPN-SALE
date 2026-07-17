# Milestone 1D-B Plan: Identity Administration Frontend

## Scope
Milestone 1D-B adds the administrator management frontend for administrators, invitations, roles, permissions, customers, administrator/customer sessions, audit logs, and security events. It integrates with the existing `/api/v1/admin/management/...` APIs from Milestone 1D-A and reuses the admin authentication client, memory-only access token store, refresh single-flight, credentials-included cookies, and CSRF header policy.

## Non-goals
Products, plans, custom pricing, wallet, ledger, orders, payments, provider instances, servers, nodes, inbounds, provisioning, subscriptions, coupons, referrals, tickets, broadcasts, resellers, and business analytics remain out of scope.

## Page inventory
- `/management` overview with no fake aggregate values.
- `/management/admins`, `/management/admins/[adminId]`, and `/management/admins/invite`.
- `/management/roles`, `/management/roles/[roleId]`, `/management/roles/new`, and `/management/permissions`.
- `/management/customers` and `/management/customers/[userId]`.
- `/management/sessions/admins` and `/management/sessions/customers`.
- `/management/audit` and `/management/audit/[eventId]`.
- `/management/security-events` and `/management/security-events/[eventId]`.
- `/management/states` plus existing safe auth state pages for unauthorized, forbidden, unavailable, and generic errors.

## Permission-aware UI policy
Navigation and actions are derived from effective permissions returned by the safe profile flow when available. The UI hides clearly unavailable sections, but hidden UI is never treated as authorization. Direct unauthorized navigation must render a controlled 403 state, and the backend remains authoritative for every permission and object-access check.

## API integration plan
A focused typed management API client serializes bounded filters, parses structured errors, preserves correlation IDs and Retry-After, retries safe reads after the existing refresh flow, sends CSRF headers for cookie-authenticated mutations, and avoids logging response bodies. Sensitive mutations remain pessimistic: status, role, session, invitation, audit, and security-event operations are shown as successful only after the server confirms them.

## Accessibility requirements
The initial locale is Persian RTL with English-ready strings. Technical identifiers render LTR. Tables have mobile card fallbacks, focus indicators are visible, destructive actions use confirmation forms, mutation feedback uses live regions where interactive components are enabled, and reduced-motion preferences disable skeleton animation.

## Acceptance criteria
Milestone 1D-B is accepted when identity administrators can use permission-aware pages for administrator, role, customer, session, audit, and security-event workflows; invitation tokens are displayed once from ephemeral component memory; structured backend errors map safely; tests cover sensitive frontend policies; and documentation matches the implemented no-commerce scope.
