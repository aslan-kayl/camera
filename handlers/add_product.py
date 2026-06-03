from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy.exc import IntegrityError

from keyboards import main_keyboard
from services.image_service import save_product_photo
from services.product_service import ProductService
from states.add_product import AddProduct
from utils.formatting import format_price
from utils.normalize import normalize_model, parse_decimal


logger = logging.getLogger(__name__)

SKIP_PHOTO_TEXT = "пропустить"

product_service = ProductService()


async def start_add_product(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddProduct.waiting_model)
    logger.info(
        "Product addition started: user_id=%s username=%r",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )
    await message.answer(
        "Введите модель товара",
        reply_markup=ReplyKeyboardRemove(),
    )


async def cancel_add_product(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Добавление товара отменено.", reply_markup=main_keyboard())


async def handle_model(message: Message, state: FSMContext) -> None:
    model = (message.text or "").strip()
    normalized_model = normalize_model(model)

    if not model:
        await message.answer("Модель не может быть пустой. Введите модель товара.")
        return

    if not normalized_model:
        from handlers.search import perform_product_search

        await state.clear()
        await perform_product_search(message, model)
        return

    await state.update_data(model=model, normalized_model=normalized_model)
    await state.set_state(AddProduct.waiting_photo)
    await message.answer(
        "Отправьте фото товара\n(или напишите <code>пропустить</code>)",
    )


async def handle_photo(message: Message, state: FSMContext, bot: Bot) -> None:
    if not message.photo:
        await message.answer(
            "Отправьте фото товара или напишите <code>пропустить</code>.",
        )
        return

    try:
        image_path = await save_product_photo(bot, message.photo[-1])
    except Exception:
        logger.exception(
            "Failed to save product photo: user_id=%s",
            message.from_user.id if message.from_user else None,
        )
        await message.answer(
            "Не удалось сохранить фото. Попробуйте отправить его ещё раз "
            "или напишите <code>пропустить</code>.",
        )
        return

    await state.update_data(image_path=image_path)
    await state.set_state(AddProduct.waiting_description)
    await message.answer("Введите описание товара")


async def skip_photo(message: Message, state: FSMContext) -> None:
    await state.update_data(image_path=None)
    await state.set_state(AddProduct.waiting_description)
    await message.answer("Введите описание товара")


async def handle_description(message: Message, state: FSMContext) -> None:
    description = (message.text or "").strip()
    await state.update_data(description=description or None)
    await state.set_state(AddProduct.waiting_price)
    await message.answer("Введите цену товара")


async def handle_price(message: Message, state: FSMContext) -> None:
    raw_price = (message.text or "").strip()
    price = parse_decimal(raw_price)

    if price <= 0:
        await message.answer("Введите корректную цену больше нуля.")
        return

    data = await state.get_data()
    model = data.get("model", "")
    normalized_model = data.get("normalized_model") or normalize_model(model)
    description = data.get("description")
    image_path = data.get("image_path")

    if not model or not normalized_model:
        logger.error(
            "Product addition failed: missing model in FSM data user_id=%s",
            message.from_user.id if message.from_user else None,
        )
        await state.clear()
        await message.answer(
            "Не удалось добавить товар: данные сессии потеряны. Начните заново.",
            reply_markup=main_keyboard(),
        )
        return

    existing_product = await product_service.get_by_normalized_model(normalized_model)
    if existing_product is not None:
        logger.info(
            "Attempt to add existing product: model=%r normalized_model=%r user_id=%s",
            model,
            normalized_model,
            message.from_user.id if message.from_user else None,
        )
        await state.clear()
        await message.answer("❌ Товар уже существует", reply_markup=main_keyboard())
        return

    try:
        product = await product_service.create_product(
            model=model,
            normalized_model=normalized_model,
            description=description,
            price=price,
            image_path=image_path,
        )
    except IntegrityError:
        logger.info(
            "Attempt to add existing product (integrity error): model=%r normalized_model=%r user_id=%s",
            model,
            normalized_model,
            message.from_user.id if message.from_user else None,
        )
        await state.clear()
        await message.answer("❌ Товар уже существует", reply_markup=main_keyboard())
        return
    except Exception:
        logger.exception(
            "Product addition failed: model=%r normalized_model=%r user_id=%s",
            model,
            normalized_model,
            message.from_user.id if message.from_user else None,
        )
        await state.clear()
        await message.answer(
            "Не удалось добавить товар. Попробуйте позже.",
            reply_markup=main_keyboard(),
        )
        return

    logger.info(
        "Product successfully added: id=%s model=%r normalized_model=%r user_id=%s",
        product.id,
        product.model,
        product.normalized_model,
        message.from_user.id if message.from_user else None,
    )
    await state.clear()
    await message.answer(
        "✅ Товар успешно добавлен\n\n"
        f"Модель:\n{product.model}\n\n"
        f"Цена:\n{format_price(product.price)}",
        reply_markup=main_keyboard(),
    )


async def handle_wrong_photo_input(message: Message) -> None:
    await message.answer(
        "Отправьте фото товара или напишите <code>пропустить</code>.",
    )


async def handle_wrong_model_input(message: Message) -> None:
    await message.answer("Введите модель товара текстом.")


async def handle_wrong_description_input(message: Message) -> None:
    await message.answer("Введите описание товара текстом.")


async def handle_wrong_price_input(message: Message) -> None:
    await message.answer("Введите цену товара числом, например: <code>12500</code> или <code>12500.50</code>.")
