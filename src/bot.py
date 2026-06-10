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
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    FSInputFile,
    Message,
    ReplyKeyboardRemove,
)

from db import close_db, init_db
from handlers.add_product import (
    cancel_add_product,
    handle_model,
    handle_photo,
    handle_price,
    handle_wrong_model_input,
    handle_wrong_photo_input,
    handle_wrong_price_input,
    start_add_product,
)
from handlers.delete_product import (
    cancel_delete_product,
    confirm_delete_product,
    handle_wrong_confirm_input,
    start_delete_product,
)
from handlers.delete_product import handle_model as delete_handle_model
from handlers.delete_product import handle_wrong_model_input as delete_handle_wrong_model_input
from handlers.update_product import (
    cancel_update_product,
    choose_field,
    handle_new_photo,
    handle_new_price,
    handle_next,
    start_update_product,
)
from handlers.update_product import handle_model as update_handle_model
from handlers.update_product import handle_new_model as update_handle_new_model
from handlers.update_product import handle_wrong_field_input as update_handle_wrong_field_input
from handlers.update_product import handle_wrong_model_input as update_handle_wrong_model_input
from handlers.update_product import handle_wrong_photo_input as update_handle_wrong_photo_input
from handlers.update_product import handle_wrong_price_input as update_handle_wrong_price_input
from import_excel import import_excel
from keyboards import (
    ADD_PRODUCT_BUTTON,
    CANCEL_BUTTON,
    DELETE_CONFIRM_BUTTON,
    DELETE_PRODUCT_BUTTON,
    SEARCH_BUTTON,
    UPDATE_PRODUCT_BUTTON,
    UPLOAD_EXCEL_BUTTON,
    main_keyboard,
)
from middlewares.access import AccessControlMiddleware
from models import Product, User
from services.access_control import admin_only
from services.audit_service import AuditAction, AuditService
from services.ocr_service import OCRService
from services.product_service import ProductService
from services.temp_file_service import cleanup_old_temp_files, delete_temp_file, save_temp_photo
from services.user_service import ROLE_ADMIN
from states.add_product import AddProduct
from states.delete_product import DeleteProduct
from states.update_product import UpdateProduct
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)
UPLOAD_DIR = Path("data/uploads")
product_service = ProductService()
ocr_service = OCRService()
audit_service = AuditService()


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


async def cmd_start(message: Message, role: str) -> None:
    telegram_id = message.from_user.id if message.from_user else None
    logger.info("User entry: telegram_id=%s role=%s", telegram_id, role)
    await message.answer(
        "Отправьте модель или часть модели товара, например: <code>7108</code>.\n"
        "Можно также отправить фото этикетки товара для OCR-поиска.",
        reply_markup=main_keyboard(is_admin=role == ROLE_ADMIN),
    )


async def handle_search_button(message: Message, role: str) -> None:
    await message.answer(
        "Введите модель или часть модели товара.",
        reply_markup=main_keyboard(is_admin=role == ROLE_ADMIN),
    )


async def ask_excel_file(message: Message, state: FSMContext) -> None:
    await state.set_state(UploadExcel.waiting_file)
    await message.answer(
        "Отправьте Excel-файл в формате <code>.xlsx</code>.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def handle_excel_upload(
    message: Message, state: FSMContext, bot: Bot, db_user: User
) -> None:
    user_id = message.from_user.id if message.from_user else None
    db_user_id = db_user.id if db_user else None

    if not message.document:
        await message.answer(
            "Пришлите Excel-файл документом (<code>.xlsx</code>), а не текстом или фото."
        )
        return

    file_name = message.document.file_name or ""
    suffix = Path(file_name).suffix.lower()
    if suffix != ".xlsx":
        logger.warning(
            "Excel import rejected: user_id=%s file=%r reason=unsupported_extension",
            user_id,
            file_name,
        )
        await message.answer(
            "❌ Неверный формат файла. Поддерживается только <code>.xlsx</code>.\n"
            "Сохраните таблицу как «Книга Excel (.xlsx)» и пришлите снова."
        )
        return

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / f"{message.document.file_unique_id}{suffix}"

    await bot.download(message.document, destination=destination)
    logger.info("Excel import started: user_id=%s file=%r", user_id, file_name)
    await message.answer("Файл получен. Начинаю импорт в PostgreSQL...")

    try:
        imported_count = await import_excel(destination)
    except Exception as exc:
        logger.exception(
            "Excel import failed: user_id=%s file=%r path=%s",
            user_id,
            file_name,
            destination,
        )
        await audit_service.log(
            AuditAction.ERROR,
            telegram_id=user_id,
            user_id=db_user_id,
            details=f"IMPORT_EXCEL failed for {file_name!r}: {exc}",
        )
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
    logger.info(
        "Excel import finished: user_id=%s file=%r imported=%s",
        user_id,
        file_name,
        imported_count,
    )
    await audit_service.log(
        AuditAction.IMPORT_EXCEL,
        telegram_id=user_id,
        user_id=db_user_id,
        details=f"file={file_name!r} imported={imported_count}",
    )
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

    user_id = message.from_user.id if message.from_user else None
    logger.info("Photo search started: user_id=%s", user_id)

    photo = message.photo[-1]
    destination = await save_temp_photo(bot, photo)

    await message.answer("Фото получил, ща два сек")

    try:
        try:
            ocr_result = await ocr_service.recognize_models(destination)
        finally:
            delete_temp_file(destination)
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
        matches = await product_service.find_by_ocr_candidates(ocr_result.candidates)
    except Exception as exc:
        logger.exception("OCR product search failed")
        await message.answer(f"OCR выполнен, но поиск не удался: <code>{escape(str(exc))}</code>")
        return

    if not matches:
        recognized = escape(", ".join(ocr_result.candidates))
        await message.answer(
            f"<b>Распознанная модель:</b> <code>{recognized}</code>\n\n"
            "Товар не найден. Попробуйте найти другим способом."
        )
        return

    # A single exact hit is the unambiguous case - send it as is.
    if len(matches) == 1 and matches[0].match_type == "exact":
        await send_product(message, matches[0].product)
        return

    # Otherwise surface every variant so a more specific (and pricier)
    # modification is never silently replaced by a cheaper one.
    if any(m.match_type == "exact" for m in matches):
        header = (
            "Найдено несколько подходящих моделей. "
            "Выберите точную модификацию (например, с суффиксом <code>/SL</code>):"
        )
    else:
        header = (
            "⚠️ Точного совпадения нет — показываю похожие модели. "
            "Сверьте точную модель и модификацию перед заказом, цены могут отличаться:"
        )
    await message.answer(header)

    for match in matches:
        await send_product(message, match.product)


async def handle_product_search(message: Message, state: FSMContext) -> None:
    await state.clear()
    user_id = message.from_user.id if message.from_user else None
    query = (message.text or "").strip()
    normalized_query = normalize_model(query)
    logger.info("Text search: user_id=%s query=%r", user_id, query)

    if len(normalized_query) < 2:
        await message.answer("Введите минимум 2 символа модели.")
        return

    products = await product_service.search_by_text(query)
    if not products:
        await message.answer("Товар не найден.")
        logger.info(
            "Product not found: user_id=%s query=%r normalized=%r",
            user_id,
            query,
            normalized_query,
        )
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
    cleanup_old_temp_files()
    await init_db()

    bot = Bot(
        token=get_bot_token(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Whitelist gate runs before any handler, so every access check happens
    # before business logic. Authorized users get a `role` injected into data.
    dp.message.outer_middleware(AccessControlMiddleware())

    dp.message.register(cmd_start, CommandStart())
    dp.message.register(cmd_start, Command("help"))
    dp.message.register(handle_search_button, F.text == SEARCH_BUTTON)
    # Catalog mutations (Excel import, add/update/delete) are ADMIN-only - the
    # admin_only guard rejects non-admins before any flow can start.
    dp.message.register(admin_only(ask_excel_file), F.text == UPLOAD_EXCEL_BUTTON)
    dp.message.register(admin_only(handle_excel_upload), UploadExcel.waiting_file, F.document)
    dp.message.register(handle_wrong_excel_upload, UploadExcel.waiting_file)

    # Add-product flow: photo -> model -> price. State-filtered handlers must
    # be registered before the catch-all photo/text search handlers below.
    dp.message.register(admin_only(start_add_product), F.text == ADD_PRODUCT_BUTTON)
    dp.message.register(cancel_add_product, Command("cancel"))
    dp.message.register(cancel_add_product, StateFilter(AddProduct), F.text == CANCEL_BUTTON)
    dp.message.register(handle_photo, AddProduct.waiting_photo, F.photo)
    dp.message.register(handle_wrong_photo_input, AddProduct.waiting_photo)
    dp.message.register(handle_model, AddProduct.waiting_model, F.text)
    dp.message.register(handle_wrong_model_input, AddProduct.waiting_model)
    dp.message.register(handle_price, AddProduct.waiting_price, F.text)
    dp.message.register(handle_wrong_price_input, AddProduct.waiting_price)

    # Delete-product flow: model -> confirm -> delete.
    dp.message.register(admin_only(start_delete_product), F.text == DELETE_PRODUCT_BUTTON)
    dp.message.register(cancel_delete_product, StateFilter(DeleteProduct), F.text == CANCEL_BUTTON)
    dp.message.register(delete_handle_model, DeleteProduct.waiting_model, F.text)
    dp.message.register(delete_handle_wrong_model_input, DeleteProduct.waiting_model)
    dp.message.register(confirm_delete_product, DeleteProduct.waiting_confirm, F.text == DELETE_CONFIRM_BUTTON)
    dp.message.register(handle_wrong_confirm_input, DeleteProduct.waiting_confirm)

    # Update-product flow: model -> choose field -> new value.
    dp.message.register(admin_only(start_update_product), F.text == UPDATE_PRODUCT_BUTTON)
    dp.message.register(cancel_update_product, StateFilter(UpdateProduct), F.text == CANCEL_BUTTON)
    dp.message.register(update_handle_model, UpdateProduct.waiting_model, F.text)
    dp.message.register(update_handle_wrong_model_input, UpdateProduct.waiting_model)
    dp.message.register(choose_field, UpdateProduct.waiting_field, F.text)
    dp.message.register(update_handle_wrong_field_input, UpdateProduct.waiting_field)
    dp.message.register(handle_new_photo, UpdateProduct.waiting_photo, F.photo)
    dp.message.register(update_handle_wrong_photo_input, UpdateProduct.waiting_photo)
    dp.message.register(update_handle_new_model, UpdateProduct.waiting_new_model, F.text)
    dp.message.register(update_handle_wrong_model_input, UpdateProduct.waiting_new_model)
    dp.message.register(handle_new_price, UpdateProduct.waiting_price, F.text)
    dp.message.register(update_handle_wrong_price_input, UpdateProduct.waiting_price)
    dp.message.register(handle_next, UpdateProduct.waiting_next, F.text)

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
