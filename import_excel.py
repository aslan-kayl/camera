from __future__ import annotations

import argparse
import asyncio
import logging
import posixpath
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db import close_db, init_db, session_scope
from models import Product
from utils import clean_string, normalize_model, parse_decimal


logger = logging.getLogger(__name__)
PRODUCT_IMAGES_DIR = Path("data/product_images")

CANONICAL_COLUMNS = {
    "model": "Наименование",
    "image_path": "Изображение",
    "description": "Описание",
    "price": "Цена",
}

COLUMN_ALIASES = {
    "model": {
        "наименование",
        "модель",
        "model",
        "imou model",
        "имоу model",
        "артикул",
        "sku",
        "код",
    },
    "image_path": {
        "изображение",
        "фото",
        "photo",
        "image",
        "image path",
        "image_path",
        "картинка",
    },
    "description": {
        "описание",
        "description",
        "desc",
        "характеристики",
        "характеристика",
    },
    "price": {
        "цена",
        "price",
        "стоимость",
        "прайс",
    },
}


def _safe_stem(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def _normalize_header(value: Any) -> str:
    text = clean_string(value)
    if text is None:
        return ""

    text = text.lower().replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def _canonical_column(value: Any) -> str | None:
    normalized = _normalize_header(value)
    if not normalized:
        return None

    for canonical_name, aliases in COLUMN_ALIASES.items():
        if normalized in aliases:
            return canonical_name

    return None


def _find_header_index(raw_df: pd.DataFrame) -> int | None:
    best_index: int | None = None
    best_score = 0

    for index, row in raw_df.iterrows():
        matched_columns = {
            canonical
            for value in row.tolist()
            if (canonical := _canonical_column(value)) is not None
        }
        score = len(matched_columns)
        if "model" in matched_columns and score > best_score:
            best_index = int(index)
            best_score = score

    if best_score >= 2:
        return best_index

    return None


def _normalize_headers(headers: list[Any]) -> list[str]:
    normalized_headers: list[str] = []
    used_headers: set[str] = set()

    for column_index, value in enumerate(headers):
        canonical_name = _canonical_column(value)
        header = CANONICAL_COLUMNS.get(canonical_name or "") or clean_string(value)
        if header is None:
            header = f"__empty_{column_index}"

        if header in used_headers:
            header = f"{header}_{column_index}"

        normalized_headers.append(header)
        used_headers.add(header)

    if CANONICAL_COLUMNS["price"] not in normalized_headers:
        description_index = (
            normalized_headers.index(CANONICAL_COLUMNS["description"])
            if CANONICAL_COLUMNS["description"] in normalized_headers
            else None
        )
        if description_index is not None:
            for index in range(description_index + 1, len(normalized_headers)):
                if normalized_headers[index].startswith("__empty_"):
                    normalized_headers[index] = CANONICAL_COLUMNS["price"]
                    break

    return normalized_headers


def _relationship_path(drawing_path: str) -> str:
    directory, filename = posixpath.split(drawing_path)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def _resolve_media_path(drawing_path: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(posixpath.dirname(drawing_path), target))


def read_products_excel(path: Path) -> pd.DataFrame:
    sheets = pd.read_excel(path, engine="openpyxl", sheet_name=None, header=None)
    product_frames: list[pd.DataFrame] = []

    for sheet_name, raw_df in sheets.items():
        header_index = _find_header_index(raw_df)
        if header_index is None:
            logger.info("Sheet skipped, product header not found: %s", sheet_name)
            continue

        headers = _normalize_headers(raw_df.iloc[header_index].tolist())
        df = raw_df.iloc[header_index + 1 :].copy()
        df.columns = headers
        df = df.dropna(how="all")
        df["__sheet_name"] = sheet_name
        product_frames.append(df)

    if not product_frames:
        raise ValueError(
            "Excel file has no product table. Supported model columns: "
            f"{', '.join(sorted(COLUMN_ALIASES['model']))}. "
            "Supported price columns: "
            f"{', '.join(sorted(COLUMN_ALIASES['price']))}."
        )

    return pd.concat(product_frames, axis=0)


def extract_embedded_images(
    path: Path,
    image_column_index: int,
    output_dir: Path = PRODUCT_IMAGES_DIR,
) -> dict[int, str]:
    """Extract images anchored to the Excel image column and return row -> path."""
    row_images: dict[int, str] = {}
    output_dir.mkdir(parents=True, exist_ok=True)

    namespaces = {
        "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    }
    embed_attr = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

    with ZipFile(path) as archive:
        drawing_paths = sorted(
            item
            for item in archive.namelist()
            if item.startswith("xl/drawings/drawing") and item.endswith(".xml")
        )

        for drawing_path in drawing_paths:
            rels_path = _relationship_path(drawing_path)
            if rels_path not in archive.namelist():
                continue

            rels_root = ET.fromstring(archive.read(rels_path))
            relationships = {
                item.attrib["Id"]: item.attrib["Target"]
                for item in rels_root
                if item.attrib.get("Type", "").endswith("/image")
            }

            drawing_root = ET.fromstring(archive.read(drawing_path))
            for anchor in list(drawing_root):
                from_node = anchor.find("xdr:from", namespaces)
                blip_node = anchor.find(".//a:blip", namespaces)
                if from_node is None or blip_node is None:
                    continue

                row = int(from_node.findtext("xdr:row", "-1", namespaces))
                col = int(from_node.findtext("xdr:col", "-1", namespaces))
                if col != image_column_index or row in row_images:
                    continue

                relationship_id = blip_node.attrib.get(embed_attr)
                target = relationships.get(relationship_id or "")
                if not target:
                    continue

                media_path = _resolve_media_path(drawing_path, target)
                if media_path not in archive.namelist():
                    continue

                extension = Path(media_path).suffix.lower() or ".png"
                output_path = output_dir / f"{_safe_stem(path.stem)}_row_{row + 1}{extension}"
                output_path.write_bytes(archive.read(media_path))
                row_images[row] = str(output_path)

    logger.info("Extracted embedded images: %s", len(row_images))
    return row_images


def validate_columns(df: pd.DataFrame) -> None:
    missing_columns = [
        column
        for column in CANONICAL_COLUMNS.values()
        if column != CANONICAL_COLUMNS["image_path"] and column not in df.columns
    ]
    if missing_columns:
        available_columns = ", ".join(str(column) for column in df.columns)
        raise ValueError(
            f"Excel file has no required columns: {', '.join(missing_columns)}. "
            f"Available columns: {available_columns}"
        )


def build_product_rows(
    df: pd.DataFrame,
    embedded_image_paths: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    validate_columns(df)
    embedded_image_paths = embedded_image_paths or {}

    products_by_model: dict[str, dict[str, Any]] = {}

    for row_index, row in df.iterrows():
        model = clean_string(row[CANONICAL_COLUMNS["model"]])
        normalized_model = normalize_model(model)
        if not model or not normalized_model:
            continue

        cell_image_path = (
            clean_string(row[CANONICAL_COLUMNS["image_path"]])
            if CANONICAL_COLUMNS["image_path"] in row.index
            else None
        )

        products_by_model[normalized_model] = {
            "model": model,
            "normalized_model": normalized_model,
            "description": clean_string(row[CANONICAL_COLUMNS["description"]]),
            "price": parse_decimal(row[CANONICAL_COLUMNS["price"]]),
            "image_path": cell_image_path or embedded_image_paths.get(int(row_index)),
        }

    return list(products_by_model.values())


async def upsert_products(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0

    statement = insert(Product).values(rows)
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_products_normalized_model",
            set_={
                "model": statement.excluded.model,
                "description": statement.excluded.description,
                "price": statement.excluded.price,
                "image_path": statement.excluded.image_path,
            },
        )
    )

    return len(rows)


async def import_excel(path: Path) -> int:
    logger.info("Reading Excel file: %s", path)
    df = await asyncio.to_thread(read_products_excel, path)
    if CANONICAL_COLUMNS["image_path"] in df.columns:
        image_column_index = list(df.columns).index(CANONICAL_COLUMNS["image_path"])
        embedded_image_paths = await asyncio.to_thread(
            extract_embedded_images,
            path,
            image_column_index,
        )
    else:
        embedded_image_paths = {}
    rows = await asyncio.to_thread(build_product_rows, df, embedded_image_paths)

    async with session_scope() as session:
        imported_count = await upsert_products(session, rows)

    logger.info("Imported products: %s", imported_count)
    return imported_count


async def search_products(query: str, limit: int = 20) -> list[Product]:
    normalized_query = normalize_model(query)
    if not normalized_query:
        return []

    async with session_scope() as session:
        result = await session.scalars(
            select(Product)
            .where(Product.normalized_model.ilike(f"%{normalized_query}%"))
            .order_by(Product.normalized_model)
            .limit(limit)
        )
        return list(result)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import products from Excel to PostgreSQL")
    parser.add_argument(
        "path",
        nargs="?",
        default="data/prices.xlsx",
        help="Path to Excel file",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate products table before import",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    path = Path(args.path)
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    await init_db(drop_existing=args.recreate)
    await import_excel(path)
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
