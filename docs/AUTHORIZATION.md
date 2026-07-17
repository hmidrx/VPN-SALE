# Authorization

RBAC with fine-grained permissions, resource ownership checks, reseller tenancy rules, separation of duties, mandatory reasons for sensitive actions, optional dual approval, and explicit authorization tests.

## Milestone 1A RBAC foundation

Milestone 1A adds persistence for roles, permissions, role-permission pairs, and administrator-role assignments. Permission codes are stable dotted machine strings. The initial idempotent seed catalog includes administrator, role, user, session, audit, and security management permissions only; no product, payment, wallet, order, panel, or provisioning permissions are introduced.

## Milestone 1D-A identity administration
Milestone 1D-A introduces backend-only management APIs protected by database-resolved permissions. Effective permissions are loaded from active role assignments for each protected request, disabled/locked administrators are denied immediately, and final active Super Admin safeguards prevent disabling or stripping the last privileged administrator path. Administrator invitations store only token hashes and return plaintext tokens once. Customer management uses documented status transitions and revokes sessions on sensitive restrictions. Audit logs are query-only and append-oriented; security events add acknowledgment/resolution workflow state. Management UI and all commerce/provider functionality remain out of scope.
