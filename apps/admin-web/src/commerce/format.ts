import { formatRial, formatToman } from '../finance/money';
import { commerceFa } from '../i18n/commerce';
export function money(rial?: number | null): string { return typeof rial === 'number' && Number.isSafeInteger(rial) ? `${formatRial(rial)} · ${formatToman(rial)}` : '—'; }
export function statusLabel(value?: string | null): string { return value && value in commerceFa.status ? commerceFa.status[value as keyof typeof commerceFa.status] : `${commerceFa.status.unknown}: ${value ?? '—'}`; }
export function iso(value?: string | null): string { return value ? new Date(value).toLocaleString('fa-IR') : '—'; }
export function humanBytes(v: unknown): string { return typeof v === 'number' ? `${Intl.NumberFormat('fa-IR').format(v)} بایت` : '—'; }
