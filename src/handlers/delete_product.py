from __future__ import annotations

import logging

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import cancel_keyboard, confirm_delete_keyboard, main_keyboard_for_role
from models import User
from services.audit_service import AuditAction, AuditService
from services.product_service import ProductService
from states.delete_product import DeleteProduct
from utils.formatting import format_price
from utils.normalize import normalize_model


logger = logging.getLogger(__name__)

product_service = ProductService()
audit_service = AuditService()


async def start_delete_product(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(DeleteProduct.waiting_model)
    logger.info(
        "Product deletion started: user_id=%s username=%r",
        message.from_user.id if message.from_user else None,
        message.from_user.username if message.from_user else None,
    )
    await message.answer(
        "Введите модель товара для удаления.",
        reply_markup=cancel_keyboard(),
    )


async def cancel_delete_product(
    message: Message, state: FSMContext, role: str | None = None
) -> None:
    await state.clear()
    await message.answer(
        "Удаление товара отменено.", reply_markup=main_keyboard_for_role(role)
    )


async def handle_model(
    message: Message, state: FSMContext, role: str | None = None
) -> None:
    model = (message.text or "").strip()
    normalized_model = normalize_model(model)

    if not model or not normalized_model:
        await message.answer(
            "Модель не может быть пустой. Введите модель товара.",
            reply_markup=cancel_keyboard(),
        )
        return

    # Use the same substring search as the catalog search so anything the user
    # can find is also deletable - an exact normalized-model match is too strict
    # (e.g. searching "laptop" must still match a model stored as "ноутбук laptop").
    products = await product_service.search_by_text(model)
    if not products:
        await state.clear()
        await message.answer(
            "❌ Товар не найден. Проверьте модель и попробуйте снова.",
            reply_markup=main_keyboard_for_role(role),
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
    await state.set_state(DeleteProduct.waiting_confirm)
    await message.answer(
        "Удалить этот товар?\n\n"
        f"Модель:\n{product.model}\n\n"
        f"Цена:\n{format_price(product.price)}",
        reply_markup=confirm_delete_keyboard(),
    )


async def confirm_delete_product(
    message: Message,
    state: FSMContext,
    db_user: User | None = None,
    role: str | None = None,
) -> None:
    data = await state.get_data()
    product_id = data.get("product_id")

    if not product_id:
        await state.clear()
        await message.answer(
            "❌ Товар не удалён: данные сессии потеряны. Начните заново.",
            reply_markup=main_keyboard_for_role(role),
        )
        return

    try:
        deleted = await product_service.delete_product(product_id)
    except Exception:
        logger.exception(
            "Product deletion failed: product_id=%s user_id=%s",
            product_id,
            message.from_user.id if message.from_user else None,
        )
        await state.clear()
        await message.answer(
            "❌ Товар не удалён. Попробуйте позже.",
            reply_markup=main_keyboard_for_role(role),
        )
        return

    await state.clear()
    if not deleted:
        await message.answer(
            "❌ Товар не удалён: он уже отсутствует в базе.",
            reply_markup=main_keyboard_for_role(role),
        )
        return

    telegram_id = message.from_user.id if message.from_user else None
    logger.info(
        "Product successfully deleted: product_id=%s user_id=%s",
        product_id,
        telegram_id,
    )
    await audit_service.log(
        AuditAction.DELETE_PRODUCT,
        telegram_id=telegram_id,
        user_id=db_user.id if db_user else None,
        details=f"id={product_id}",
    )
    await message.answer("✅ Товар удалён.", reply_markup=main_keyboard_for_role(role))


async def handle_wrong_model_input(message: Message) -> None:
    await message.answer("Введите модель товара текстом.", reply_markup=cancel_keyboard())


async def handle_wrong_confirm_input(message: Message) -> None:
    await message.answer(
        "Нажмите «✅ Удалить» для подтверждения или «❌ Отмена».",
        reply_markup=confirm_delete_keyboard(),
    )
