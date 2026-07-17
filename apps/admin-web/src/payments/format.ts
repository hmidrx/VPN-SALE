export function formatRial(v?: number | null): string { if (!Number.isInteger(v)) return '—'; const n = Number(v); return `${new Intl.NumberFormat('fa-IR').format(n)} ریال`; }
export function formatToman(v?: number | null): string { if (!Number.isInteger(v)) return '—'; const n = Number(v); return `${new Intl.NumberFormat('fa-IR').format(Math.trunc(n/10))} تومان مشتق‌شده`; }
export function safeDate(v?: string | null): string { return v ? new Intl.DateTimeFormat('fa-IR-u-ca-persian',{dateStyle:'medium',timeStyle:'short'}).format(new Date(v)) : '—'; }
export function ltr(v?: string | number | null): string { return v == null || v === '' ? '—' : String(v); }
export const secretKeyPattern = /(secret|token|signature|authorization|cookie|password|credential|api[_-]?key|raw|body|fingerprint|idempotency)/i;
export function safeMetadata(input?: Record<string, unknown>): Record<string, string> { const out: Record<string,string>={}; for (const [k,v] of Object.entries(input??{}).slice(0,20)) { out[k]=secretKeyPattern.test(k) ? 'مخفی' : String(v).slice(0,160); } return out; }
