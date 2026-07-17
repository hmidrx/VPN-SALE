import type { AdminProfile } from "../auth/types";
export const catalogPermissions = ["catalog.read","catalog.create","catalog.update","catalog.publish","pricing.read","pricing.manage","quotes.read"] as const;
export function catalogEffectivePermissions(profile?: Partial<AdminProfile> & { effective_permissions?: string[] }): Set<string> { const p = new Set(profile?.effective_permissions ?? []); if (profile?.roles?.includes("super_admin")) catalogPermissions.forEach((x)=>p.add(x)); return p; }
export function canCatalog(perms: Set<string>, required: string[]): boolean { return required.length === 0 || required.some((p)=>perms.has(p)); }
export const productVersionPolicy = { publishedReadOnly: true, editPublishedCreatesDraft: true, serverAuthoritativePublication: true };
export function conflictMessage(code: string): string { return ({duplicate_category:"این دسته قبلاً ثبت شده است.", duplicate_product:"این محصول قبلاً ثبت شده است.", invalid_publication:"اعتبارسنجی انتشار ناموفق بود.", pricing_unavailable:"قیمت‌گذاری در دسترس نیست.", catalog_403:"دسترسی کافی ندارید."} as Record<string,string>)[code] ?? "خطای امن کاتالوگ رخ داد؛ شناسه همبستگی را به تیم عملیات بدهید."; }
