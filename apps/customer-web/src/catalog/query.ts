import type { ProductType } from "./types";
export type CatalogQuery = { category?: string; type?: ProductType; q?: string };
const safe = /^[a-zA-Z0-9_-]{1,80}$/;
export function parseCatalogQuery(search: string): CatalogQuery { const p = new URLSearchParams(search); const out: CatalogQuery = {}; const category = p.get("category"); const type = p.get("type"); const q = p.get("q"); if (category && safe.test(category)) out.category = category; if (type === "FIXED_PLAN" || type === "CUSTOM_PLAN") out.type = type; if (q) out.q = q.trim().slice(0, 80); return out; }
export function serializeCatalogQuery(q: CatalogQuery): string { const p = new URLSearchParams(); if (q.category && safe.test(q.category)) p.set("category", q.category); if (q.type) p.set("type", q.type); if (q.q) p.set("q", q.q.trim().slice(0, 80)); return p.toString(); }
