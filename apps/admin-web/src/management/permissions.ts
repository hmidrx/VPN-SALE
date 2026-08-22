import type { AdminProfile } from "../auth/types";
export type NavItem = { href: string; label: string; permissions: string[] };
export const managementNav: NavItem[] = [
  { href: "/management", label: "نمای کلی", permissions: ["admins.read", "users.read", "audit.read", "security.read"] },
  { href: "/catalog", label: "کاتالوگ", permissions: ["catalog.read", "pricing.read", "quotes.read"] },
  { href: "/management/finance", label: "مالی", permissions: ["wallets.read", "ledger.read", "ledger.reconcile","providers.read","providers.manage","providers.manage_credentials","providers.test_connection","providers.sync","providers.read_inventory","providers.read_diagnostics","providers.certify","configuration.read","configuration.manage","configuration.preview","configuration.publish","configuration.rollback","branding.read","branding.manage","themes.read","themes.manage","content_templates.read","content_templates.manage","feature_flags.read","feature_flags.manage","navigation.read","navigation.manage","telegram_menus.read","telegram_menus.manage","media_assets.read","media_assets.manage"] },
  { href: "/management/admins", label: "مدیران", permissions: ["admins.read"] },
  { href: "/management/roles", label: "نقش‌ها و مجوزها", permissions: ["roles.read"] },
  { href: "/management/customers", label: "مشتریان", permissions: ["users.read"] },
  { href: "/management/sessions/admins", label: "نشست‌ها", permissions: ["sessions.read"] },
  { href: "/management/audit", label: "حسابرسی", permissions: ["audit.read"] },
  { href: "/management/security-events", label: "مرکز امنیت", permissions: ["security.read"] },
  { href: "/management/providers", label: "ارائه‌دهندگان", permissions: ["providers.read"] },
  { href: "/security/profile", label: "امنیت شخصی", permissions: [] }
];
export function effectivePermissions(profile?: Partial<AdminProfile> & { effective_permissions?: string[] }): Set<string> { return new Set(profile?.effective_permissions ?? profile?.roles?.flatMap((r) => r === "super_admin" ? ["admins.read","admins.invite","admins.update","admins.disable","admins.unlock","admins.roles.manage","roles.read","roles.create","roles.update","roles.permissions.manage","users.read","users.activate","users.suspend","users.block","users.deactivate","sessions.read","sessions.revoke","audit.read","security.read","security.acknowledge","security.manage","catalog.read","catalog.create","catalog.update","catalog.publish","pricing.read","pricing.manage","quotes.read","wallets.read","wallets.adjust","wallets.freeze","wallets.policy.manage","ledger.read","ledger.reconcile","providers.read","providers.manage","providers.manage_credentials","providers.test_connection","providers.sync","providers.read_inventory","providers.read_diagnostics","providers.certify"] : []) ?? []); }
export function can(perms: Set<string>, required: string[]): boolean { return required.length === 0 || required.some((p) => perms.has(p)); }
export function visibleNav(perms: Set<string>): NavItem[] { return managementNav.filter((item) => can(perms, item.permissions)); }
