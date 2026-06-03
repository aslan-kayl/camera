from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging

from sqlalchemy import case, or_, select

from db import SessionLocal, session_scope
from models import Product
from utils.normalize import normalize_model
from utils.search import escape_ilike


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductMatch:
    product: Product
    score: float
    match_type: str
    query: str


class ProductService:
    async def get_by_normalized_model(self, normalized_model: str) -> Product | None:
        if not normalized_model:
            return None

        async with SessionLocal() as session:
            return await session.scalar(
                select(Product).where(Product.normalized_model == normalized_model)
            )

    async def create_product(
        self,
        *,
        model: str,
        normalized_model: str,
        description: str | None,
        price: Decimal,
        image_path: str | None = None,
    ) -> Product:
        product = Product(
            model=model,
            normalized_model=normalized_model,
            description=description,
            price=price,
            image_path=image_path,
        )

        async with session_scope() as session:
            session.add(product)
            await session.flush()
            await session.refresh(product)

        logger.info(
            "Product created: id=%s model=%r normalized_model=%r",
            product.id,
            product.model,
            product.normalized_model,
        )
        return product

    async def search_by_text(self, query: str) -> list[Product]:
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []

        normalized_query = normalize_model(cleaned_query)
        escaped_query = escape_ilike(cleaned_query)
        pattern = f"%{escaped_query}%"
        prefix_pattern = f"{escaped_query}%"

        search_conditions = [Product.model.ilike(pattern, escape="\\")]
        if normalized_query:
            search_conditions.append(Product.normalized_model == normalized_query)

        async with SessionLocal() as session:
            statement = (
                select(Product)
                .where(or_(*search_conditions))
                .order_by(
                    case((Product.normalized_model == normalized_query, 0), else_=1),
                    case((Product.model.ilike(escaped_query, escape="\\"), 0), else_=1),
                    case((Product.model.ilike(prefix_pattern, escape="\\"), 0), else_=1),
                    Product.model,
                )
            )
            result = await session.scalars(statement)
            products = list(result)

        logger.info(
            "Text product search query=%r normalized=%r count=%s",
            cleaned_query,
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
