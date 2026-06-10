from __future__ import annotations

import re


_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")
_MODEL_SEPARATORS_RE = re.compile(r"[-_.]")
_DIGITS_RE = re.compile(r"\d")


def is_model_like_query(query: str) -> bool:
    """Return True when the query should be searched as a device model."""
    text = (query or "").strip()
    if not text:
        return False

    if _CYRILLIC_RE.search(text):
        return False

    if _DIGITS_RE.search(text):
        return True

    if _MODEL_SEPARATORS_RE.search(text):
        return True

    return False


def escape_ilike(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
