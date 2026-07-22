from __future__ import annotations

from datetime import UTC, datetime

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa_digits(value: int | str) -> str:
    return str(value).translate(PERSIAN_DIGITS)


def format_toman(amount_minor: int | None) -> str:
    if amount_minor is None:
        return "نامشخص"
    return f"{fa_digits(f'{amount_minor:,}')} تومان"


def format_count(count: int | None, singular: str = "مورد") -> str:
    if count is None:
        return "نامشخص"
    return f"{fa_digits(count)} {singular}"


def format_traffic_gb(gb: int | None) -> str:
    if gb is None:
        return "نامشخص"
    return f"{fa_digits(gb)} گیگابایت"


def _gregorian_to_jalali(year: int, month: int, day: int) -> tuple[int, int, int]:
    gy = year - 1600
    gm = month - 1
    gd = day - 1
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    for i in range(gm):
        g_day_no += g_days_in_month[i]
    if gm > 1 and ((year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)):
        g_day_no += 1
    g_day_no += gd
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm = 0
    while jm < 11 and j_day_no >= j_days_in_month[jm]:
        j_day_no -= j_days_in_month[jm]
        jm += 1
    return jy, jm + 1, j_day_no + 1


def format_datetime(value: datetime | None) -> str:
    if value is None:
        return "—"
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    jy, jm, jd = _gregorian_to_jalali(normalized.year, normalized.month, normalized.day)
    return fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d}، {normalized.hour:02d}:{normalized.minute:02d}")


def format_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    normalized = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    jy, jm, jd = _gregorian_to_jalali(normalized.year, normalized.month, normalized.day)
    return fa_digits(f"{jy:04d}/{jm:02d}/{jd:02d}")
