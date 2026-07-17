import type { AdminProfile } from "../auth/types";
export type NavItem = { href: string; label: string; permissions: string[] };
export const managementNav: NavItem[] = [
  { href: "/management", label: "نمای کلی", permissions: ["admins.read", "users.read", "audit.read", "security.read"] },
  { href: "/management/admins", label: "مدیران", permissions: ["admins.read"] },
  { href: "/management/roles", label: "نقش‌ها و مجوزها", permissions: ["roles.read"] },
  { href: "/management/customers", label: "مشتریان", permissions: ["users.read"] },
  { href: "/management/sessions/admins", label: "نشست‌ها", permissions: ["sessions.read"] },
  { href: "/management/audit", label: "حسابرسی", permissions: ["audit.read"] },
  { href: "/management/security-events", label: "مرکز امنیت", permissions: ["security.read"] },
  { href: "/security/profile", label: "امنیت شخصی", permissions: [] }
];
export function effectivePermissions(profile?: Partial<AdminProfile> & { effective_permissions?: string[] }): Set<string> { return new Set(profile?.effective_permissions ?? profile?.roles?.flatMap((r) => r === "super_admin" ? ["admins.read","admins.invite","admins.update","admins.disable","admins.unlock","admins.roles.manage","roles.read","roles.create","roles.update","roles.permissions.manage","users.read","users.activate","users.suspend","users.block","users.deactivate","sessions.read","sessions.revoke","audit.read","security.read","security.acknowledge","security.manage"] : []) ?? []); }
export function can(perms: Set<string>, required: string[]): boolean { return required.length === 0 || required.some((p) => perms.has(p)); }
export function visibleNav(perms: Set<string>): NavItem[] { return managementNav.filter((item) => can(perms, item.permissions)); }
