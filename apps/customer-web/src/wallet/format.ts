import { formatDate } from "../i18n/fa";
import type {
  CreditStatus,
  ReservationStatus,
  TransactionDirection,
  WalletBucket,
  WalletStatus,
} from "./types";

export type MoneyPresentationErrorCode =
  | "INVALID_RIAL_AMOUNT"
  | "NON_EXACT_TOMAN_AMOUNT"
  | "INVALID_TOMAN_INPUT"
  | "UNSAFE_TOMAN_AMOUNT";

export class MoneyPresentationError extends Error {
  constructor(public readonly code: MoneyPresentationErrorCode) {
    super(code);
    this.name = "MoneyPresentationError";
  }
}

export function assertSafeRialAmount(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new MoneyPresentationError("INVALID_RIAL_AMOUNT");
  }
  return value;
}

/** Kept as the API response validator's compatibility entry point. */
export function assertSafeRial(value: unknown, _field = "amount"): number {
  return assertSafeRialAmount(value);
}

export function rialToExactToman(value: unknown): number {
  const rial = assertSafeRialAmount(value);
  if (rial % 10 !== 0) {
    throw new MoneyPresentationError("NON_EXACT_TOMAN_AMOUNT");
  }
  return rial / 10;
}

export function tomanToExactRial(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new MoneyPresentationError("INVALID_TOMAN_INPUT");
  }
  if (value > Math.floor(Number.MAX_SAFE_INTEGER / 10)) {
    throw new MoneyPresentationError("UNSAFE_TOMAN_AMOUNT");
  }
  return value * 10;
}

export function normalizePersianDigits(value: string): string {
  return value
    .replace(/[۰-۹]/g, (digit) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(digit)))
    .replace(/[٠-٩]/g, (digit) => String("٠١٢٣٤٥٦٧٨٩".indexOf(digit)));
}

const EDITABLE_GROUPING = /[\u066C\u060C,\s]/g;

/**
 * Converts an editable Toman value to canonical ASCII digits. Currency words and
 * every character other than supported digits/grouping are rejected.
 */
export function displayTomanToCanonicalDigits(value: string): string {
  const normalized = normalizePersianDigits(value.trim());
  if (normalized === "") return "";
  if (/[^0-9\u066C\u060C,\s]/.test(normalized)) {
    throw new MoneyPresentationError("INVALID_TOMAN_INPUT");
  }
  const digits = normalized.replace(EDITABLE_GROUPING, "");
  if (!/^[0-9]+$/.test(digits)) {
    throw new MoneyPresentationError("INVALID_TOMAN_INPUT");
  }
  const canonical = digits.replace(/^0+(?=\d)/, "");
  const parsed = Number(canonical);
  if (
    !Number.isSafeInteger(parsed) ||
    parsed > Math.floor(Number.MAX_SAFE_INTEGER / 10)
  ) {
    throw new MoneyPresentationError("UNSAFE_TOMAN_AMOUNT");
  }
  return canonical;
}

export const normalizeTomanEditableInput = displayTomanToCanonicalDigits;

export function tomanDigitsToDisplay(value: string): string {
  if (value === "") return "";
  if (!/^[0-9]+$/.test(value))
    throw new MoneyPresentationError("INVALID_TOMAN_INPUT");
  const parsed = Number(value);
  if (
    !Number.isSafeInteger(parsed) ||
    parsed > Math.floor(Number.MAX_SAFE_INTEGER / 10)
  ) {
    throw new MoneyPresentationError("UNSAFE_TOMAN_AMOUNT");
  }
  return new Intl.NumberFormat("fa-IR", {
    useGrouping: true,
    maximumFractionDigits: 0,
  }).format(parsed);
}

export function formatEditableToman(value: string): string {
  return tomanDigitsToDisplay(displayTomanToCanonicalDigits(value));
}

export function parseTomanInput(raw: string, requirePositive = true): number {
  const canonical = displayTomanToCanonicalDigits(raw);
  if (canonical === "") throw new MoneyPresentationError("INVALID_TOMAN_INPUT");
  const toman = Number(canonical);
  if (!Number.isSafeInteger(toman) || (requirePositive && toman === 0)) {
    throw new MoneyPresentationError("UNSAFE_TOMAN_AMOUNT");
  }
  return toman;
}

export function formatToman(value: number, locale = "fa-IR"): string {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new MoneyPresentationError("INVALID_TOMAN_INPUT");
  }
  return `${new Intl.NumberFormat(locale).format(value)} تومان`;
}

export function formatTomanFromRial(value: number, locale = "fa-IR"): string {
  return formatToman(rialToExactToman(value), locale);
}

const bucketFa: Record<string, string> = {
  CASH: "نقدی",
  REFUND: "بازگشت وجه",
  GIFT: "هدیه",
  REFERRAL: "معرفی دوستان",
  PROMOTIONAL: "اعتبار تبلیغاتی",
  ADMIN_GRANT: "اعتبار مدیریتی",
};
export const bucketLabel = (code: WalletBucket): string =>
  bucketFa[code] ?? "اعتبار دیگر";
export const walletStatusLabel = (status: WalletStatus): string =>
  status === "ACTIVE" ? "فعال" : status === "FROZEN" ? "محدود" : "بسته";
export const transactionDirectionLabel = (
  direction?: TransactionDirection,
): string =>
  direction === "INCOMING"
    ? "افزایش موجودی"
    : direction === "OUTGOING"
      ? "کاهش موجودی"
      : "بدون تغییر";
export const creditStatusLabel = (status: CreditStatus): string =>
  status === "ACTIVE"
    ? "فعال"
    : status === "EXHAUSTED"
      ? "مصرف‌شده"
      : status === "EXPIRED"
        ? "منقضی"
        : status === "REVERSED"
          ? "برگشت‌خورده"
          : "نامشخص";
export const reservationStatusLabel = (status: ReservationStatus): string =>
  status === "ACTIVE"
    ? "فعال"
    : status === "RELEASED"
      ? "آزادشده"
      : status === "EXPIRED"
        ? "منقضی"
        : status === "CAPTURED"
          ? "برداشت‌شده"
          : status === "CANCELLED"
            ? "لغوشده"
            : "نامشخص";
export function transactionTypeLabel(type: string): string {
  return (
    (
      {
        ADMIN_CREDIT: "افزایش اعتبار",
        ADMIN_DEBIT: "کاهش اعتبار",
        REFUND_CREDIT: "بازگشت وجه",
        PROMOTIONAL_CREDIT: "اعتبار تبلیغاتی",
        REFERRAL_CREDIT: "معرفی دوستان",
        GIFT_CREDIT: "هدیه",
        CREDIT_EXPIRATION: "انقضای اعتبار",
        RESERVATION_CREATED: "رزرو مبلغ",
        RESERVATION_RELEASED: "آزادسازی رزرو",
        RESERVATION_EXPIRED: "انقضای رزرو",
        RESERVATION_CAPTURED: "برداشت رزرو",
        REVERSAL: "بازگشت تراکنش",
      } as Record<string, string>
    )[type] ?? "تراکنش کیف پول"
  );
}
export const displayDate = formatDate;
