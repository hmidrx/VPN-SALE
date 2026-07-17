export const COMPARISON_LIMIT = 3;
export function normalizeComparison(ids: string[]): string[] { const safe = ids.filter((id) => /^[a-zA-Z0-9_-]{1,120}$/.test(id)); return Array.from(new Set(safe)).slice(0, COMPARISON_LIMIT); }
