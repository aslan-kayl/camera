from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any


# Keep Latin and Cyrillic letters plus digits - products may be named in either
# alphabet, so both must survive normalization for search to find them.
_NON_ALNUM_RE = re.compile(r"[^A-ZА-Я0-9]+")


def normalize_model(value: str | None) -> str:
    """Normalize product model for exact and fuzzy matching."""
    if not value:
        return ""

    # Fold Ё to Е so "ёлка" and "елка" match, then drop everything that is not
    # a Latin/Cyrillic letter or a digit.
    upper_value = str(value).upper().replace("Ё", "Е")
    return _NON_ALNUM_RE.sub("", upper_value)


def clean_string(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None

    return text


def parse_decimal(value: Any) -> Decimal:
    text = clean_string(value)
    if text is None:
        return Decimal("0")

    normalized = text.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    normalized = re.sub(r"[^0-9.\-]", "", normalized)

    try:
        return Decimal(normalized)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def parse_int(value: Any) -> int:
    text = clean_string(value)
    if text is None:
        return 0

    normalized = text.replace(" ", "").replace("\u00a0", "")
    match = re.search(r"-?\d+", normalized)
    if match is None:
        return 0

    return int(match.group(0))
