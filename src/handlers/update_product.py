from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.exc import IntegrityError

from keyboards import (
    CONTINUE_UPDATE_BUTTON,
    MAIN_MENU_BUTTON,
    UPDATE_MODEL_BUTTON,
    UPDATE_PHOTO_BUTTON,
    UPDATE_PRICE_BUTTON,
    cancel_keyboard,
    main_keyboard,
    update_field_keyboard,
    update_next_keyboard,
)
from models import User
from services.audit_service import AuditAction, AuditService
from services.image_service import save_product_photo
from services.product_service import ProductService
from states.update_product import UpdateProduct
from utils.formatting import format_price
from utils.normalize import normalize_model, parse_decimal


logger = logging.getLogger(__name__)

product_service = ProductService()
audit_service = AuditService()


async def start_update_product(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(UpdateProduct.waiting_model)
    logger.info(
        "Product update started: user_id=%s username=%r",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )
    await message.answer(
        "Введите модель товара для обновления.",
        reply_markup=cancel_keyboard(),
    )


async def cancel_update_product(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Обновление товара отменено.", reply_markup=main_keyboard())


async def handle_model(message: Message, state: FSMContext) -> None:
    model = (message.text or "").strip()
    normalized_model = normalize_model(model)

    if not model or not normalized_model:
        await message.answer(
            "Модель не может быть пустой. Введите модель товара.",
            reply_markup=cancel_keyboard(),
        )
        return

    # Same substring search as the catalog/delete flow so anything the user can
    # find is also editable - an exact normalized-model match is too strict.
    products = await product_service.search_by_text(model)
    if not products:
        await state.clear()
        await message.answer(
            "❌ Товар не найден. Проверьте модель и попробуйте снова.",
            reply_markup=main_keyboard(),
        )
        return

    exact = [p for p in products if p.normalized_model == normalized_model]
    if exact:
        product = exact[0]
    elif len(products) == 1:
        product = products[0]
    else:
        preview = "\n".join(f"• {p.model}" for p in products[:10])
        await message.answer(
            "Найдено несколько товаров. Уточните модель:\n\n"
            f"{preview}",
            reply_markup=cancel_keyboard(),
        )
        return

    await state.update_data(product_id=product.id)
    await _show_field_menu(message, state, product)


async def _show_field_menu(message: Message, state: FSMContext, product) -> None:
    await state.set_state(UpdateProduct.waiting_field)
    await message.answer(
        "Что обновить?\n\n"
        f"Модель:\n{product.model}\n\n"
        f"Цена:\n{format_price(product.price)}",
        reply_markup=update_field_keyboard(),
    )


async def choose_field(message: Message, state: FSMContext) -> None:
    choice = (message.text or "").strip()

    if choice == UPDATE_PHOTO_BUTTON:
        await state.set_state(UpdateProduct.waiting_photo)
        await message.answer("Отправьте новое фото товара.", reply_markup=cancel_keyboard())
    elif choice == UPDATE_MODEL_BUTTON:
        await state.set_state(UpdateProduct.waiting_new_model)
        await message.answer("Введите новую модель товара.", reply_markup=cancel_keyboard())
    elif choice == UPDATE_PRICE_BUTTON:
        await state.set_state(UpdateProduct.waiting_price)
        await message.answer("Введите новую цену товара.", reply_markup=cancel_keyboard())
    else:
        await message.answer(
            "Выберите, что обновить, с помощью кнопок.",
            reply_markup=update_field_keyboard(),
        )


async def _get_product_id(message: Message, state: FSMContext) -> int | None:
    data = await state.get_data()
    product_id = data.get("product_id")
    if not product_id:
        await state.clear()
        await message.answer(
            "❌ Товар не обновлён: данные сессии потеряны. Начните заново.",
            reply_markup=main_keyboard(),
        )
        return None
    return product_id


async def _finish_success(
    message: Message, state: FSMContext, product, db_user: User | None = None
) -> None:
    # Keep product_id in the FSM so the user can continue editing the same item.
    await state.update_data(product_id=product.id)
    await state.set_state(UpdateProduct.waiting_next)
    telegram_id = message.from_user.id if message.from_user else None
    logger.info(
        "Product successfully updated: id=%s user_id=%s",
        product.id,
        telegram_id,
    )
    await audit_service.log(
        AuditAction.UPDATE_PRODUCT,
        telegram_id=telegram_id,
        user_id=db_user.id if db_user else None,
        details=f"id={product.id} model={product.model!r} price={product.price}",
    )
    await message.answer(
        "✅ Товар успешно изменён\n\n"
        f"Модель:\n{product.model}\n\n"
        f"Цена:\n{format_price(product.price)}\n\n"
        "Желаете продолжить обновление или перейти в главное меню?",
        reply_markup=update_next_keyboard(),
    )


async def handle_next(message: Message, state: FSMContext) -> None:
    choice = (message.text or "").strip()

    if choice == CONTINUE_UPDATE_BUTTON:
        product_id = await _get_product_id(message, state)
        if product_id is None:
            return
        product = await product_service.get_by_id(product_id)
        if product is None:
            await state.clear()
            await message.answer(
                "❌ Товар больше не найден. Начните заново.",
                reply_markup=main_keyboard(),
            )
            return
        await _show_field_menu(message, state, product)
    elif choice == MAIN_MENU_BUTTON:
        await state.clear()
        await message.answer("Главное меню.", reply_markup=main_keyboard())
    else:
        await message.answer(
            "Выберите действие с помощью кнопок.",
            reply_markup=update_next_keyboard(),
        )


async def _finish_failure(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("❌ Товар не обновлён. Попробуйте позже.", reply_markup=main_keyboard())


async def handle_new_photo(
    message: Message, state: FSMContext, bot: Bot, db_user: User | None = None
) -> None:
    product_id = await _get_product_id(message, state)
    if product_id is None:
        return

    if not message.photo:
        await message.answer("Отправьте фото товара.", reply_markup=cancel_keyboard())
        return

    try:
        image_path = await save_product_photo(bot, message.photo[-1])
        product = await product_service.update_product(product_id, image_path=image_path)
    except Exception:
        logger.exception("Product photo update failed: product_id=%s", product_id)
        await _finish_failure(message, state)
        return

    if product is None:
        await _finish_failure(message, state)
        return

    await _finish_success(message, state, product, db_user)


async def handle_new_model(
    message: Message, state: FSMContext, db_user: User | None = None
) -> None:
    product_id = await _get_product_id(message, state)
    if product_id is None:
        return

    model = (message.text or "").strip()
    normalized_model = normalize_model(model)

    if not model or not normalized_model:
        await message.answer(
            "Модель не может быть пустой. Введите модель товара.",
            reply_markup=cancel_keyboard(),
        )
        return

    existing = await product_service.get_by_normalized_model(normalized_model)
    if existing is not None and existing.id != product_id:
        await state.clear()
        await message.answer(
            "❌ Товар не обновлён: такой товар уже существует.",
            reply_markup=main_keyboard(),
        )
        return

    try:
        product = await product_service.update_product(
            product_id,
            model=model,
            normalized_model=normalized_model,
        )
    except IntegrityError:
        await state.clear()
        await message.answer(
            "❌ Товар не обновлён: такой товар уже существует.",
            reply_markup=main_keyboard(),
        )
        return
    except Exception:
        logger.exception("Product model update failed: product_id=%s", product_id)
        await _finish_failure(message, state)
        return

    if product is None:
        await _finish_failure(message, state)
        return

    await _finish_success(message, state, product, db_user)


async def handle_new_price(
    message: Message, state: FSMContext, db_user: User | None = None
) -> None:
    product_id = await _get_product_id(message, state)
    if product_id is None:
        return

    price = parse_decimal((message.text or "").strip())
    if price <= 0:
        await message.answer(
            "Введите корректную цену больше нуля.",
            reply_markup=cancel_keyboard(),
        )
        return

    try:
        product = await product_service.update_product(product_id, price=price)
    except Exception:
        logger.exception("Product price update failed: product_id=%s", product_id)
        await _finish_failure(message, state)
        return

    if product is None:
        await _finish_failure(message, state)
        return

    await _finish_success(message, state, product, db_user)


async def handle_wrong_model_input(message: Message) -> None:
    await message.answer("Введите модель товара текстом.", reply_markup=cancel_keyboard())


async def handle_wrong_field_input(message: Message) -> None:
    await message.answer(
        "Выберите, что обновить, с помощью кнопок.",
        reply_markup=update_field_keyboard(),
    )


async def handle_wrong_photo_input(message: Message) -> None:
    await message.answer("Отправьте фото товара.", reply_markup=cancel_keyboard())


async def handle_wrong_price_input(message: Message) -> None:
    await message.answer(
        "Введите цену товара числом, например: <code>12500</code> или <code>12500.50</code>.",
        reply_markup=cancel_keyboard(),
    )
