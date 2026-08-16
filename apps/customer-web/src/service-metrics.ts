export type TimeMetric = {
  percentage: number | null;
  remainingDays: number | null;
  unlimited: boolean;
};
export function clampPercentage(value: number): number {
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 0;
}
export function calculateTimeMetric(
  startsAt: string | null,
  expiresAt: string | null,
  now = Date.now(),
): TimeMetric {
  if (!expiresAt)
    return { percentage: null, remainingDays: null, unlimited: true };
  const expiry = Date.parse(expiresAt);
  if (!Number.isFinite(expiry))
    return { percentage: null, remainingDays: null, unlimited: false };
  const remaining = Math.max(0, expiry - now);
  const remainingDays = Math.ceil(remaining / 86_400_000);
  if (!startsAt)
    return { percentage: null, remainingDays, unlimited: false };
  const start = Date.parse(startsAt),
    total = expiry - start;
  if (!Number.isFinite(start) || total <= 0)
    return { percentage: null, remainingDays, unlimited: false };
  return {
    percentage: clampPercentage((remaining / total) * 100),
    remainingDays,
    unlimited: false,
  };
}
export function formatBytes(value: number | null, unlimited = false): string {
  if (unlimited) return "نامحدود";
  if (value === null || !Number.isFinite(value) || value < 0) return "نامشخص";
  const units = ["بایت", "کیبی‌بایت", "مبی‌بایت", "گیگابایت", "تبی‌بایت"];
  let amount = value,
    unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  const precision = Number.isInteger(amount) ? 0 : 1;
  return `${amount.toLocaleString("fa-IR", { maximumFractionDigits: precision })} ${units[unit]}`;
}
