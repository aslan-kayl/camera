from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import logging

from sqlalchemy import case, select

from db import SessionLocal
from models import Product
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)

# Sentinel distinguishing "argument not provided" from an explicit None, so an
# update can clear an optional field (e.g. description) as well as leave it.
_UNSET = object()


@dataclass(frozen=True)
class ProductMatch:
    product: Product
    score: float
    match_type: str
    query: str


class ProductService:
    async def get_by_id(self, product_id: int) -> Product | None:
        async with SessionLocal() as session:
            return await session.get(Product, product_id)

    async def get_by_normalized_model(self, normalized_model: str) -> Product | None:
        if not normalized_model:
            return None

        async with SessionLocal() as session:
            statement = select(Product).where(Product.normalized_model == normalized_model)
            return await session.scalar(statement)

    async def create_product(
        self,
        *,
        model: str,
        normalized_model: str,
        price: Decimal,
        description: str | None = None,
        image_path: str | None = None,
        stock: int | None = None,
    ) -> Product:
        async with SessionLocal() as session:
            product = Product(
                model=model,
                normalized_model=normalized_model,
                description=description,
                price=price,
                image_path=image_path,
                stock=stock,
            )
            session.add(product)
            await session.commit()
            await session.refresh(product)

        logger.info(
            "Product created: id=%s model=%r normalized_model=%r",
            product.id,
            product.model,
            product.normalized_model,
        )
        return product

    async def update_product(
        self,
        product_id: int,
        *,
        model: str | None = None,
        normalized_model: str | None = None,
        price: Decimal | None = None,
        image_path: str | None = None,
        description: str | None | object = _UNSET,
    ) -> Product | None:
        async with SessionLocal() as session:
            product = await session.get(Product, product_id)
            if product is None:
                return None

            if model is not None:
                product.model = model
            if normalized_model is not None:
                product.normalized_model = normalized_model
            if price is not None:
                product.price = price
            if image_path is not None:
                product.image_path = image_path
            # _UNSET means "leave as is"; an explicit None clears the description.
            if description is not _UNSET:
                product.description = description  # type: ignore[assignment]

            await session.commit()
            await session.refresh(product)

        logger.info(
            "Product updated: id=%s model=%r normalized_model=%r",
            product.id,
            product.model,
            product.normalized_model,
        )
        return product

    async def delete_product(self, product_id: int) -> bool:
        async with SessionLocal() as session:
            product = await session.get(Product, product_id)
            if product is None:
                return False
            await session.delete(product)
            await session.commit()

        logger.info("Product deleted: id=%s", product_id)
        return True

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
        limit: int = 10,
    ) -> list[ProductMatch]:
        """Find products for OCR candidates, ranked best-to-worst.

        Returns every relevant variant instead of a single guess so that a more
        specific (and usually more expensive) modification such as ``…LI2U/SL`` is
        never silently replaced by a shorter ``…LI2U``. Longer candidates and
        longer models are preferred, mirroring the substring logic of the manual
        text search so anything that exists in the catalog is actually found.
        """
        normalized_candidates = [
            candidate for candidate in dict.fromkeys(normalize_model(item) for item in candidates)
            if len(candidate) >= 5
        ]
        # Longer candidates are the more specific modifications - try them first.
        normalized_candidates.sort(key=len, reverse=True)
        if not normalized_candidates:
            return []

        async with SessionLocal() as session:
            all_products = list(await session.scalars(select(Product)))

        return self._rank_ocr_matches(
            candidates=normalized_candidates,
            products=all_products,
            fuzzy_threshold=fuzzy_threshold,
            limit=limit,
        )

    def _rank_ocr_matches(
        self,
        candidates: list[str],
        products: list[Product],
        fuzzy_threshold: int,
        limit: int,
    ) -> list[ProductMatch]:
        matches: list[ProductMatch] = []
        seen: set[int] = set()

        def add(product: Product, score: float, match_type: str, query: str) -> None:
            if product.id in seen:
                return
            seen.add(product.id)
            matches.append(ProductMatch(product, score, match_type, query))

        # 1. Exact: candidate == normalized_model. Most specific model first.
        for candidate in candidates:
            exact = sorted(
                (p for p in products if p.normalized_model == candidate),
                key=lambda p: len(p.normalized_model),
                reverse=True,
            )
            for product in exact:
                add(product, 100.0, "exact", candidate)

        # 2. Partial: same substring matching as the manual text search, in both
        #    directions, so a dropped suffix (OCR misses "/SL") still surfaces the
        #    longer SKU and a candidate with OCR noise still finds the real model.
        for candidate in candidates:
            partial = [
                product
                for product in products
                if product.normalized_model
                and product.id not in seen
                and (candidate in product.normalized_model or product.normalized_model in candidate)
            ]
            partial.sort(key=lambda p: len(p.normalized_model), reverse=True)
            for product in partial:
                add(product, 90.0, "partial", candidate)

        # 3. Fuzzy: only as a last resort, when nothing matched exactly or partially.
        if not matches:
            for product, score, query in self._fuzzy_matches(candidates, products, fuzzy_threshold):
                add(product, score, "fuzzy", query)

        if len(matches) > limit:
            logger.info("OCR matches truncated from %s to %s", len(matches), limit)
            matches = matches[:limit]

        logger.info(
            "OCR product search candidates=%s matches=%s",
            candidates,
            [(m.match_type, m.product.model, m.score) for m in matches],
        )
        return matches

    def _fuzzy_matches(
        self,
        candidates: list[str],
        products: list[Product],
        fuzzy_threshold: int,
    ) -> list[tuple[Product, float, str]]:
        if not candidates or not products:
            return []

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
        if not choices:
            return []

        best_by_product: dict[int, tuple[Product, float, str]] = {}
        for candidate in candidates:
            for matched_model, score, _ in process.extract(
                candidate,
                choices.keys(),
                scorer=fuzz.WRatio,
                score_cutoff=fuzzy_threshold,
                limit=5,
            ):
                product = choices[matched_model]
                previous = best_by_product.get(product.id)
                if previous is None or score > previous[1]:
                    best_by_product[product.id] = (product, float(score), candidate)

        return sorted(best_by_product.values(), key=lambda item: item[1], reverse=True)
