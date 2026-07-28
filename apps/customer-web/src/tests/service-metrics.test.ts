import { describe, expect, it } from "vitest";
import {
  calculateTimeMetric,
  clampPercentage,
  formatBytes,
} from "../service-metrics";

describe("service metrics", () => {
  it("calculates remaining time from authoritative boundaries", () => {
    expect(
      calculateTimeMetric(
        "2026-01-01T00:00:00Z",
        "2026-01-31T00:00:00Z",
        Date.parse("2026-01-16T00:00:00Z"),
      ),
    ).toEqual({ percentage: 50, remainingDays: 15, unlimited: false });
  });
  it("handles expired, invalid and no-expiry services", () => {
    expect(
      calculateTimeMetric(
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
        Date.parse("2026-01-03T00:00:00Z"),
      ).percentage,
    ).toBe(0);
    expect(calculateTimeMetric("bad", "also-bad").percentage).toBeNull();
    expect(calculateTimeMetric("2026-01-01T00:00:00Z", null).unlimited).toBe(
      true,
    );
  });
  it("formats binary traffic with Persian numerals", () => {
    expect(formatBytes(50 * 1024 ** 3)).toBe("۵۰ گیگابایت");
    expect(formatBytes(32.2 * 1024 ** 3)).toBe("۳۲٫۲ گیگابایت");
    expect(formatBytes(null)).toBe("نامشخص");
    expect(formatBytes(null, true)).toBe("نامحدود");
  });
  it("clamps percentages", () => {
    expect(clampPercentage(-3)).toBe(0);
    expect(clampPercentage(104)).toBe(100);
    expect(clampPercentage(Number.NaN)).toBe(0);
  });
});
