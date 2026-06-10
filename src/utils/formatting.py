from __future__ import annotations

from decimal import Decimal


def format_price(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")
