from __future__ import annotations

from dataclasses import dataclass
import logging

from sqlalchemy import case, select

from db import SessionLocal
from models import Product
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductMatch:
    product: Product
    score: float
    match_type: str
    query: str


class ProductService:
    async def search_by_text(self, query: str) -> list[Product]:
        normalized_query = normalize_model(query)
        if not normalized_query:
            return []

        async with SessionLocal() as session:
            statement = (
                select(Product)
                .where(Product.normalized_model.ilike(f"%{normalized_query}%"))
                .order_by(
                    case((Product.normalized_model == normalized_query, 0), else_=1),
                    Product.normalized_model,
                )
            )
            result = await session.scalars(statement)
            products = list(result)

        logger.info(
            "Text product search query=%r normalized=%r count=%s",
            query,
            normalized_query,
            len(products),
        )
        return products

    async def find_by_ocr_candidates(
        self,
        candidates: list[str],
        fuzzy_threshold: int = 78,
    ) -> ProductMatch | None:
        normalized_candidates = [
            candidate for candidate in dict.fromkeys(normalize_model(item) for item in candidates)
            if len(candidate) >= 5
        ]
        if not normalized_candidates:
            return None

        async with SessionLocal() as session:
            exact_result = await session.scalars(
                select(Product).where(Product.normalized_model.in_(normalized_candidates))
            )
            exact_products = list(exact_result)
            if exact_products:
                product_by_model = {
                    product.normalized_model: product for product in exact_products
                }
                for candidate in normalized_candidates:
                    product = product_by_model.get(candidate)
                    if product is not None:
                        logger.info("OCR exact product match: %s", product.model)
                        return ProductMatch(product, 100.0, "exact", candidate)

            all_products = list(await session.scalars(select(Product)))

        return self._find_fuzzy_match(
            candidates=normalized_candidates,
            products=all_products,
            fuzzy_threshold=fuzzy_threshold,
        )

    def _find_fuzzy_match(
        self,
        candidates: list[str],
        products: list[Product],
        fuzzy_threshold: int,
    ) -> ProductMatch | None:
        if not candidates or not products:
            return None

        try:
            from rapidfuzz import fuzz, process
        except ImportError as exc:
            logger.exception("rapidfuzz is not installed")
            raise RuntimeError("rapidfuzz is not installed") from exc

        choices = {
            product.normalized_model: product
            for product in products
            if product.normalized_model
        }

        best_match: ProductMatch | None = None
        for candidate in candidates:
            result = process.extractOne(
                candidate,
                choices.keys(),
                scorer=fuzz.WRatio,
                score_cutoff=fuzzy_threshold,
            )
            if result is None:
                continue

            matched_model, score, _ = result
            product = choices[matched_model]
            if best_match is None or score > best_match.score:
                best_match = ProductMatch(product, float(score), "fuzzy", candidate)

        if best_match is not None:
            logger.info(
                "OCR fuzzy product match: query=%s product=%s score=%s",
                best_match.query,
                best_match.product.model,
                best_match.score,
            )

        return best_match
