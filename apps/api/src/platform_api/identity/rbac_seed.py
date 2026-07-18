from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from vpnsale_domain.identity import validate_permission_code

from .models import PermissionModel, RoleModel

INITIAL_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("admins.read", "Read administrator records"),
    ("admins.create", "Create administrator records"),
    ("admins.update", "Update administrator records"),
    ("admins.disable", "Disable administrator records"),
    ("admins.roles.manage", "Manage administrator role assignments"),
    ("roles.read", "Read roles"),
    ("roles.create", "Create roles"),
    ("roles.update", "Update roles"),
    ("roles.permissions.manage", "Manage role permissions"),
    ("users.read", "Read users"),
    ("users.update", "Update users"),
    ("users.suspend", "Suspend users"),
    ("sessions.read", "Read sessions"),
    ("sessions.revoke", "Revoke sessions"),
    ("audit.read", "Read audit logs"),
    ("security.manage", "Manage security settings"),
    ("admins.invite", "Invite administrators"),
    ("admins.unlock", "Unlock administrators"),
    ("users.block", "Block users"),
    ("users.activate", "Activate users"),
    ("users.deactivate", "Deactivate users"),
    ("security.read", "Read security events"),
    ("security.acknowledge", "Acknowledge security events"),
    ("catalog.read", "Read catalog administration data"),
    ("catalog.create", "Create catalog administration data"),
    ("catalog.update", "Update catalog administration data"),
    ("catalog.publish", "Publish catalog product versions"),
    ("pricing.read", "Read pricing previews and rules"),
    ("pricing.manage", "Manage price lists and pricing rules"),
    ("quotes.read", "Read customer quote records"),
    ("customers.read", "Read customer directory and profiles"),
    ("customers.manage", "Manage customer administration"),
    ("customers.manage_status", "Manage customer lifecycle status"),
    ("customers.manage_security", "Manage customer sessions and security"),
    ("customers.notes.read", "Read internal customer notes"),
    ("customers.notes.manage", "Manage internal customer notes"),
    ("customers.tags.read", "Read customer tags"),
    ("customers.tags.manage", "Manage customer tags"),
    ("customers.bulk.read", "Read customer bulk operations"),
    ("customers.bulk.manage", "Manage customer bulk operations"),
    ("customers.export", "Export allowlisted customer data"),
    ("customer_wallets.read", "Read customer wallet inspection"),
    ("customer_wallets.freeze", "Freeze and unfreeze customer wallets"),
    ("customer_wallets.adjust", "Request customer wallet adjustments"),
    ("customer_wallets.adjust_cash", "Request cash adjustments"),
    ("customer_wallets.approve_adjustment", "Approve high-risk adjustments"),
    ("fleet.read", "Read fleet hierarchy"),
    ("fleet.read_health", "Read fleet health evidence"),
    ("fleet.read_capacity", "Read fleet capacity"),
    ("fleet.manage_health_policies", "Manage fleet health policies"),
    ("fleet.manage_capacity_policies", "Manage fleet capacity policies"),
    ("fleet.maintenance.read", "Read fleet maintenance"),
    ("fleet.maintenance.manage", "Manage fleet maintenance"),
    ("fleet.maintenance.approve", "Approve fleet maintenance"),
    ("fleet.drain.read", "Read fleet drains"),
    ("fleet.drain.manage", "Manage fleet drains"),
    ("fleet.drain.execute", "Execute fleet drains"),
    ("fleet.failover.read", "Read fleet failover proposals"),
    ("fleet.failover.manage", "Manage fleet failover proposals"),
    ("fleet.failover.approve", "Approve fleet failover proposals"),
    ("fleet.bulk.read", "Read fleet bulk operations"),
    ("fleet.bulk.manage", "Manage fleet bulk operations"),
    ("fleet.bulk.approve", "Approve fleet bulk operations"),
    ("fleet.runbooks.read", "Read fleet runbooks"),
    ("fleet.runbooks.manage", "Manage fleet runbooks"),
    ("fleet.runbooks.publish", "Publish fleet runbooks"),
    ("fleet.runbooks.execute", "Execute fleet runbooks"),
    ("fleet.manual_review.manage", "Manage fleet manual reviews"),
    ("operations.readiness.read", "Read operations readiness reports"),
    ("operations.releases.read", "Read release evidence"),
    ("operations.releases.manage", "Manage release evidence"),
    ("operations.backups.read", "Read backup manifests"),
    ("operations.backups.execute", "Execute backups"),
    ("operations.restore_drills.read", "Read restore drills"),
    ("operations.restore_drills.execute", "Execute restore drills"),
    ("operations.provider_certification.read", "Read provider certification"),
    ("operations.provider_certification.execute", "Execute provider certification"),
    ("operations.runbooks.read", "Read operational runbooks"),
    ("quality.read", "Read quality release console"),
    ("quality.performance.read", "Read performance evidence"),
    ("quality.performance.execute", "Execute registered performance profiles"),
    ("quality.security.read", "Read security assessment evidence"),
    ("quality.security.execute", "Execute registered security profiles"),
    ("quality.chaos.read", "Read chaos evidence"),
    ("quality.chaos.execute", "Execute registered chaos profiles"),
    ("quality.defects.read", "Read release defects"),
    ("quality.defects.manage", "Manage release defects"),
    ("releases.candidates.read", "Read release candidates"),
    ("releases.candidates.manage", "Manage release candidates"),
    ("releases.gates.review", "Review release gates"),
    ("releases.go_no_go.read", "Read Go No-Go reports"),
    ("releases.go_no_go.review", "Review Go No-Go decisions"),
)
INITIAL_ROLES: tuple[tuple[str, str], ...] = (
    ("super_admin", "Super Admin"),
    ("security_admin", "Security Administrator"),
    ("support_viewer", "Support Viewer"),
    ("auditor", "Auditor"),
)


def seed_initial_rbac(session: Session) -> None:
    for code, description in INITIAL_PERMISSIONS:
        validate_permission_code(code)
        existing = session.scalar(select(PermissionModel).where(PermissionModel.code == code))
        if existing is None:
            session.add(PermissionModel(code=code, description=description))
    for machine_name, display_name in INITIAL_ROLES:
        existing = session.scalar(select(RoleModel).where(RoleModel.machine_name == machine_name))
        if existing is None:
            session.add(
                RoleModel(
                    machine_name=machine_name, display_name=display_name, built_in=True, active=True
                )
            )
    session.flush()
