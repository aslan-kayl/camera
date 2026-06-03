from __future__ import annotations

import asyncio
import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import ADD_PRODUCT_BUTTON, UPLOAD_EXCEL_BUTTON, main_keyboard
from services.product_service import ProductService
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 15
MENU_BUTTONS = {UPLOAD_EXCEL_BUTTON, ADD_PRODUCT_BUTTON}

product_service = ProductService()


def is_menu_button(text: str | None) -> bool:
    return (text or "").strip() in MENU_BUTTONS


async def perform_product_search(message: Message, query: str) -> None:
    from bot import send_product

    cleaned_query = query.strip()
    if not cleaned_query:
        await message.answer("Введите запрос для поиска.")
        return

    normalized_query = normalize_model(cleaned_query) or None
    search_type = "text"

    try:
        products = await product_service.search_by_text(cleaned_query)
    except Exception:
        logger.exception(
            "Product search failed: query=%r user_id=%s",
            cleaned_query,
            message.from_user.id if message.from_user else None,
        )
        await message.answer("Не удалось выполнить поиск. Попробуйте позже.")
        return

    if not products:
        await message.answer("Товар не найден.")
        logger.info(
            "Product not found for query=%r normalized=%r search_type=%s",
            cleaned_query,
            normalized_query,
            search_type,
        )
        return

    total_count = len(products)
    visible_products = products[:MAX_SEARCH_RESULTS]

    logger.info(
        "Found %s products for query=%r normalized=%r search_type=%s showing=%s",
        total_count,
        cleaned_query,
        normalized_query,
        search_type,
        len(visible_products),
    )

    if total_count > MAX_SEARCH_RESULTS:
        await message.answer(
            f"Найдено товаров: <b>{total_count}</b>. "
            f"Показаны первые <b>{MAX_SEARCH_RESULTS}</b>. "
            "Уточните запрос, чтобы сузить результат.",
        )
    else:
        await message.answer(f"Найдено товаров: <b>{total_count}</b>.")

    for index, product in enumerate(visible_products):
        try:
            await send_product(message, product)
        except Exception:
            logger.exception(
                "Failed to send product search result: query=%r product_id=%s model=%r",
                cleaned_query,
                product.id,
                product.model,
            )
            await message.answer(
                f"Не удалось отправить карточку товара: <code>{product.model}</code>",
            )

        if index + 1 < len(visible_products):
            await asyncio.sleep(0.05)


async def handle_product_search(message: Message, state: FSMContext) -> None:
    if is_menu_button(message.text):
        return

    await state.clear()
    await perform_product_search(message, message.text or "")
