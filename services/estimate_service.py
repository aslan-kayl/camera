from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging
import re

from models import Product
from services.product_service import ProductService


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EstimateItem:
    query: str
    quantity: int
    product: Product | None

    @property
    def line_total(self) -> Decimal:
        if self.product is None:
            return Decimal("0")

        return self.product.price * self.quantity


@dataclass(frozen=True)
class EstimateResult:
    items: list[EstimateItem]

    @property
    def has_missing_items(self) -> bool:
        return any(item.product is None for item in self.items)

    @property
    def total(self) -> Decimal:
        return sum((item.line_total for item in self.items), Decimal("0"))


class EstimateService:
    def __init__(self, product_service: ProductService | None = None) -> None:
        self.product_service = product_service or ProductService()

    async def build_estimate(self, text: str) -> EstimateResult:
        parsed_items = parse_estimate_text(text)
        items: list[EstimateItem] = []

        for quantity, query in parsed_items:
            product = await self.product_service.find_exact_by_text(query)
            items.append(EstimateItem(query=query, quantity=quantity, product=product))

        logger.info(
            "Estimate built: items=%s missing=%s total=%s",
            len(items),
            sum(1 for item in items if item.product is None),
            sum((item.line_total for item in items), Decimal("0")),
        )
        return EstimateResult(items=items)


def parse_estimate_text(text: str) -> list[tuple[int, str]]:
    parts = [part.strip() for part in re.split(r"\s*\+\s*", text) if part.strip()]
    parsed_items: list[tuple[int, str]] = []

    for part in parts:
        quantity = 1
        query = part

        prefix_match = re.match(r"^(?P<quantity>\d+)\s*(?:x|х|шт\.?)?\s+(?P<query>.+)$", part, re.IGNORECASE)
        suffix_match = re.match(r"^(?P<query>.+?)\s*(?:x|х|\*)\s*(?P<quantity>\d+)$", part, re.IGNORECASE)

        if prefix_match:
            quantity = int(prefix_match.group("quantity"))
            query = prefix_match.group("query")
        elif suffix_match:
            quantity = int(suffix_match.group("quantity"))
            query = suffix_match.group("query")

        query = query.strip()
        if query:
            parsed_items.append((max(quantity, 1), query))

    return parsed_items
