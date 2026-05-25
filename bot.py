from __future__ import annotations

import asyncio
from decimal import Decimal
from html import escape
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    FSInputFile,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from db import close_db, init_db
from import_excel import import_excel
from models import Product
from services.ocr_service import OCRService
from services.product_service import ProductService
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)
UPLOAD_DIR = Path("data/uploads")
OCR_UPLOAD_DIR = Path("data/ocr_uploads")
SEARCH_BUTTON = "Поиск товара"
UPLOAD_EXCEL_BUTTON = "Загрузить Excel"
product_service = ProductService()
ocr_service = OCRService()


class UploadExcel(StatesGroup):
    waiting_file = State()


def setup_logging() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def get_bot_token() -> str:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is required")

    return token


def get_admin_ids() -> set[int]:
    raw_value = os.getenv("ADMIN_IDS", "")
    if not raw_value.strip():
        return set()

    admin_ids: set[int] = set()
    for value in raw_value.split(","):
        value = value.strip()
        if value:
            try:
                admin_ids.add(int(value))
            except ValueError:
                logger.warning("Invalid ADMIN_IDS value ignored: %r", value)

    return admin_ids


def is_admin(user_id: int | None) -> bool:
    admin_ids = get_admin_ids()
    return bool(user_id) and (not admin_ids or user_id in admin_ids)


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=SEARCH_BUTTON)],
            [KeyboardButton(text=UPLOAD_EXCEL_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Введите модель или выберите действие",
    )


def format_price(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", " ")


def truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value

    return value[:limit].rstrip() + "..."


def format_product(product: Product, description_limit: int = 2500) -> str:
    raw_description = product.description or "Нет описания"
    description = escape(truncate_text(raw_description, description_limit))
    stock = product.stock if product.stock is not None else "не указан"
    return (
        f"<b>{escape(product.model)}</b>\n"
        f"Модель: <code>{escape(product.model)}</code>\n"
        f"Цена: <b>{format_price(product.price)}</b>\n"
        f"Остаток: <b>{stock}</b>\n"
        f"Описание: {description}"
    )


def build_photo(value: str | None) -> str | FSInputFile | None:
    if not value:
        return None

    if value.startswith(("http://", "https://")):
        return value

    path = Path(value)
    if path.exists() and path.is_file():
        return FSInputFile(path)

    return None


async def cmd_start(message: Message) -> None:
    await message.answer(
        "Отправьте модель или часть модели товара, например: <code>7108</code>.\n"
        "Можно также отправить фото этикетки товара для OCR-поиска.",
        reply_markup=main_keyboard(),
    )


async def handle_search_button(message: Message) -> None:
    await message.answer(
        "Введите модель или часть модели товара.",
        reply_markup=main_keyboard(),
    )


async def ask_excel_file(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id if message.from_user else None):
        await message.answer("Загрузка Excel доступна только администратору.")
        return

    await state.set_state(UploadExcel.waiting_file)
    await message.answer(
        "Отправьте Excel-файл в формате <code>.xlsx</code> или <code>.xlsm</code>.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def handle_excel_upload(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.document:
        await message.answer("Пришлите Excel-файл документом.")
        return

    file_name = message.document.file_name or ""
    suffix = Path(file_name).suffix.lower()
    if suffix not in {".xlsx", ".xlsm"}:
        await message.answer("Поддерживаются только Excel-файлы <code>.xlsx</code> и <code>.xlsm</code>.")
        return

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / f"{message.document.file_unique_id}{suffix}"

    await bot.download(message.document, destination=destination)
    await message.answer("Файл получен. Начинаю импорт в PostgreSQL...")

    try:
        imported_count = await import_excel(destination)
    except Exception as exc:
        logger.exception("Excel import failed: %s", destination)
        await message.answer(
            "Не удалось импортировать Excel. Проверьте колонки: "
            "<code>Наименование/Model/IMOU Model</code>, "
            "<code>Изображение/Фото/Image</code>, "
            "<code>Описание/Description</code>, "
            "<code>Цена/Price</code>.\n\n"
            f"Ошибка: <code>{escape(str(exc))}</code>",
            reply_markup=main_keyboard(),
        )
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"Импорт завершен. Загружено товаров: <b>{imported_count}</b>.",
        reply_markup=main_keyboard(),
    )


async def handle_wrong_excel_upload(message: Message) -> None:
    await message.answer("Сейчас нужно отправить Excel-файл документом.")


async def send_product(message: Message, product: Product, prefix: str | None = None) -> None:
    photo = build_photo(product.image_path)
    caption = format_product(product, description_limit=800 if photo is not None else 2500)
    if prefix:
        caption = f"{prefix}\n\n{caption}"

    if photo is not None:
        await message.answer_photo(photo=photo, caption=caption)
        return

    await message.answer(caption)


async def handle_photo_search(message: Message, bot: Bot) -> None:
    if not message.photo:
        return

    OCR_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    photo = message.photo[-1]
    destination = OCR_UPLOAD_DIR / f"{photo.file_unique_id}.jpg"

    await bot.download(photo, destination=destination)
    await message.answer("Фото получил, ща два сек")

    try:
        ocr_result = await ocr_service.recognize_models(destination)
    except Exception as exc:
        logger.exception("OCR failed for image: %s", destination)
        await message.answer(f"Не удалось распознать фото: <code>{escape(str(exc))}</code>")
        return

    if not ocr_result.candidates:
        text_preview = escape(truncate_text(ocr_result.text or "текст не распознан", 700))
        await message.answer(
            "Не удалось выделить модель товара из OCR-текста.\n\n"
            f"<b>Распознанный текст:</b>\n<code>{text_preview}</code>"
        )
        return

    try:
        match = await product_service.find_by_ocr_candidates(ocr_result.candidates)
    except Exception as exc:
        logger.exception("OCR product search failed")
        await message.answer(f"OCR выполнен, но поиск не удался: <code>{escape(str(exc))}</code>")
        return

    if match is None:
        await message.answer(
            "Модель распознана, но товара в базе не найдено."
        )
        return

    await send_product(message, match.product)


async def handle_product_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    query = (message.text or "").strip()
    normalized_query = normalize_model(query)

    if len(normalized_query) < 2:
        await message.answer("Введите минимум 2 символа модели.")
        return

    products = await product_service.search_by_text(query)
    if not products:
        await message.answer("Товар не найден.")
        logger.info("Product not found for query=%r normalized=%r", query, normalized_query)
        return

    logger.info(
        "Found %s products for query=%r normalized=%r",
        len(products),
        query,
        normalized_query,
    )

    await message.answer(f"Найдено товаров: <b>{len(products)}</b>.")

    for product in products:
        await send_product(message, product)


async def main() -> None:
    setup_logging()
    await init_db()

    bot = Bot(
        token=get_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_start, Command("help"))
    dp.message.register(handle_search_button, F.text == SEARCH_BUTTON)
    dp.message.register(ask_excel_file, F.text == UPLOAD_EXCEL_BUTTON)
    dp.message.register(handle_excel_upload, UploadExcel.waiting_file, F.document)
    dp.message.register(handle_wrong_excel_upload, UploadExcel.waiting_file)
    dp.message.register(handle_photo_search, F.photo)
    dp.message.register(handle_product_search, F.text)

    try:
        logger.info("Bot polling started")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
