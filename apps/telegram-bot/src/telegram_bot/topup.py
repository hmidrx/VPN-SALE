from __future__ import annotations

MINIMUM_TOPUP_TOMAN = 100_000
TOPUP_PRESETS = (100_000, 250_000, 500_000, 1_000_000, 2_000_000)

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_SEPARATORS = frozenset(" ,٬،_\u00a0")


def parse_toman_amount(value: str) -> int:
    normalized = value.translate(_DIGITS).strip()
    compact = "".join(character for character in normalized if character not in _SEPARATORS)
    if not compact or not compact.isascii() or not compact.isdecimal():
        raise ValueError("invalid amount")
    amount = int(compact)
    if amount < MINIMUM_TOPUP_TOMAN:
        raise ValueError("amount below minimum")
    return amount


def toman_to_rial(amount_toman: int) -> int:
    if amount_toman < MINIMUM_TOPUP_TOMAN:
        raise ValueError("amount below minimum")
    return amount_toman * 10
