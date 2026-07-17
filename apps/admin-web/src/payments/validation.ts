import type { Page } from './types';
export function assertIntegerRial(value: unknown, field='amount_rial'): number { if (!Number.isInteger(value) || Number(value) <= 0) throw new Error(`malformed ${field}`); return Number(value); }
export function validatePage<T>(value: Page<T>): Page<T> { if (!value || !Array.isArray(value.items)) throw new Error('malformed cursor page'); if (value.next_cursor != null && typeof value.next_cursor !== 'string') throw new Error('malformed cursor'); return value; }
export function validateCurrency(v: unknown): string { if (v !== 'IRR') throw new Error('unsupported currency'); return 'IRR'; }
export function validateVersion(v: unknown): number { if (!Number.isInteger(v) || Number(v)<0) throw new Error('malformed version'); return Number(v); }
export function validateMethodAmounts(min?: number|null,max?: number|null): void { if (min!=null) assertIntegerRial(min,'min_amount_rial'); if (max!=null) assertIntegerRial(max,'max_amount_rial'); if (min!=null && max!=null && min>max) throw new Error('minimum exceeds maximum'); }
