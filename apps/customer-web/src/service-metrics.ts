export type TimeMetric = { percentage: number | null; remainingDays: number | null; unlimited: boolean };
export function clampPercentage(value: number): number {
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
}
export function calculateTimeMetric(startsAt: string, expiresAt: string | null, now = Date.now()): TimeMetric {
  if (!expiresAt) return { percentage: null, remainingDays: null, unlimited: true };
  const start = Date.parse(startsAt), expiry = Date.parse(expiresAt), total = expiry - start;
  if (!Number.isFinite(start) || !Number.isFinite(expiry) || total <= 0) return { percentage: null, remainingDays: null, unlimited: false };
  const remaining = Math.max(0, expiry - now);
  return { percentage: clampPercentage(remaining / total * 100), remainingDays: Math.ceil(remaining / 86_400_000), unlimited: false };
}
export function formatBytes(value: number | null, unlimited = false): string {
  if (unlimited) return "نامحدود";
  if (value === null || !Number.isFinite(value) || value < 0) return "نامشخص";
  const units = ["بایت", "کیبی‌بایت", "مبی‌بایت", "گیگابایت", "تبی‌بایت"];
  let amount = value, unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  const precision = Number.isInteger(amount) ? 0 : 1;
  return `${amount.toLocaleString("fa-IR", { maximumFractionDigits: precision })} ${units[unit]}`;
}
