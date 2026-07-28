import { describe, expect, it } from "vitest";
import { MoneyPresentationError, formatTomanFromRial, normalizePersianDigits, parseTomanInput, rialToExactToman, tomanToExactRial } from "../wallet/format";

describe("exact Toman presentation", () => {
  it("formats zero and exact Rial with one currency label", () => {
    expect(formatTomanFromRial(0)).toBe("۰ تومان");
    expect(formatTomanFromRial(2_500_000)).toBe("۲۵۰٬۰۰۰ تومان");
    expect(formatTomanFromRial(2_500_000).match(/تومان/g)).toHaveLength(1);
  });
  it.each([true, -10, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])("rejects unsafe Rial %p", (value) => {
    expect(() => rialToExactToman(value)).toThrow(MoneyPresentationError);
  });
  it("fails closed instead of rounding a remaining Rial", () => {
    expect(() => rialToExactToman(101)).toThrowError(expect.objectContaining({ code: "NON_EXACT_TOMAN_AMOUNT" }));
  });
});

describe("Toman input boundary", () => {
  it.each([["۲۵۰٬۰۰۰", 250_000], ["٢٥٠٬٠٠٠", 250_000], ["250,000", 250_000], ["250 000", 250_000]])("parses %s", (input, expected) => expect(parseTomanInput(input)).toBe(expected));
  it.each(["", "0", "-1", "+1", "1.5", "1e5", "۱۲x", "Infinity"])("rejects %s", (input) => expect(() => parseTomanInput(input)).toThrow(MoneyPresentationError));
  it("normalizes both Persian and Arabic digits", () => expect(normalizePersianDigits("۱۲٣٤")).toBe("1234"));
  it("multiplies by exactly ten with safe integer arithmetic", () => expect(tomanToExactRial(parseTomanInput("۲۵۰٬۰۰۰"))).toBe(2_500_000));
  it("accepts the largest safe convertible Toman and rejects the next value", () => {
    const maximum = Math.floor(Number.MAX_SAFE_INTEGER / 10);
    expect(tomanToExactRial(maximum)).toBe(maximum * 10);
    expect(() => tomanToExactRial(maximum + 1)).toThrowError(expect.objectContaining({ code: "UNSAFE_TOMAN_AMOUNT" }));
  });
});
