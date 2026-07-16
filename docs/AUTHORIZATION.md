# Authorization

RBAC with fine-grained permissions, resource ownership checks, reseller tenancy rules, separation of duties, mandatory reasons for sensitive actions, optional dual approval, and explicit authorization tests.

## Milestone 1A RBAC foundation

Milestone 1A adds persistence for roles, permissions, role-permission pairs, and administrator-role assignments. Permission codes are stable dotted machine strings. The initial idempotent seed catalog includes administrator, role, user, session, audit, and security management permissions only; no product, payment, wallet, order, panel, or provisioning permissions are introduced.
