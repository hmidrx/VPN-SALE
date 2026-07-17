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
