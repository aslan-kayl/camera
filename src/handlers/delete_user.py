from __future__ import annotations

import logging
import re

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import (
    BACK_BUTTON,
    DELETE_USER_NO_BUTTON,
    DELETE_USER_YES_BUTTON,
    ROLE_ADMIN_CHOICE_BUTTON,
    ROLE_USER_CHOICE_BUTTON,
    delete_user_confirm_keyboard,
    delete_user_role_keyboard,
    main_keyboard_for_role,
    users_list_keyboard,
)
from services.user_service import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER, UserService
from states.delete_user import DeleteUser


logger = logging.getLogger(__name__)

user_service = UserService()

_ID_RE = re.compile(r"id:(\d+)")
_ROLE_PLURAL = {ROLE_ADMIN: "администраторов", ROLE_USER: "пользователей"}


def _format_user_button(user) -> str:
    name = user.name or str(user.telegram_id)
    return f"{name} (id:{user.telegram_id})"


def _parse_user_id(text: str | None) -> int | None:
    match = _ID_RE.search(text or "")
    return int(match.group(1)) if match else None


async def _show_role_choice(message: Message, state: FSMContext) -> None:
    await state.set_state(DeleteUser.waiting_role)
    await message.answer(
        "Кого удалить — обычного пользователя или администратора?",
        reply_markup=delete_user_role_keyboard(),
    )


async def _show_user_list(message: Message, state: FSMContext, role: str) -> None:
    users = await user_service.list_by_role(role)
    if not users:
        await state.set_state(DeleteUser.waiting_role)
        await message.answer(
            f"Список {_ROLE_PLURAL[role]} пуст.",
            reply_markup=delete_user_role_keyboard(),
        )
        return

    await state.update_data(role=role)
    await state.set_state(DeleteUser.waiting_user)
    await message.answer(
        f"Выберите, кого удалить из {_ROLE_PLURAL[role]}:",
        reply_markup=users_list_keyboard([_format_user_button(u) for u in users]),
    )


async def start_delete_user(message: Message, state: FSMContext) -> None:
    await state.clear()
    logger.info(
        "Delete-user started: user_id=%s",
        message.from_user.id if message.from_user else None,
    )
    await _show_role_choice(message, state)


async def choose_delete_role(message: Message, state: FSMContext) -> None:
    choice = (message.text or "").strip()
    if choice == BACK_BUTTON:
        await state.clear()
        await message.answer(
            "Главное меню.", reply_markup=main_keyboard_for_role(ROLE_SUPER_ADMIN)
        )
    elif choice == ROLE_USER_CHOICE_BUTTON:
        await _show_user_list(message, state, ROLE_USER)
    elif choice == ROLE_ADMIN_CHOICE_BUTTON:
        await _show_user_list(message, state, ROLE_ADMIN)
    else:
        await message.answer(
            "Выберите роль с помощью кнопок.",
            reply_markup=delete_user_role_keyboard(),
        )


async def select_user(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == BACK_BUTTON:
        await _show_role_choice(message, state)
        return

    data = await state.get_data()
    role = data.get("role")
    telegram_id = _parse_user_id(text)
    if telegram_id is None:
        await message.answer("Выберите пользователя из списка кнопкой.")
        return

    user = await user_service.get_by_telegram_id(telegram_id)
    if user is None or user.role != role:
        await message.answer("Пользователь не найден, список обновлён.")
        await _show_user_list(message, state, role)
        return

    await state.update_data(target_telegram_id=telegram_id, target_name=user.name)
    await state.set_state(DeleteUser.waiting_confirm)
    await message.answer(
        f"Действительно удалить «{user.name}» (id {telegram_id})?",
        reply_markup=delete_user_confirm_keyboard(),
    )


async def confirm_delete_user(message: Message, state: FSMContext) -> None:
    choice = (message.text or "").strip()
    data = await state.get_data()
    role = data.get("role")
    telegram_id = data.get("target_telegram_id")

    if choice == DELETE_USER_NO_BUTTON:
        # "Нет" returns to the list the super admin was in.
        await _show_user_list(message, state, role)
        return

    if choice != DELETE_USER_YES_BUTTON:
        await message.answer(
            "Нажмите «Да» или «Нет».", reply_markup=delete_user_confirm_keyboard()
        )
        return

    if not telegram_id:
        await state.clear()
        await message.answer(
            "❌ Данные сессии потеряны. Начните заново.",
            reply_markup=main_keyboard_for_role(ROLE_SUPER_ADMIN),
        )
        return

    deleted = await user_service.delete_by_telegram_id(telegram_id)
    name = data.get("target_name") or telegram_id
    if deleted:
        logger.info(
            "User removed: telegram_id=%s by_user_id=%s",
            telegram_id,
            message.from_user.id if message.from_user else None,
        )
        await message.answer(f"✅ Удалён: {name} (id {telegram_id}).")
    else:
        await message.answer("❌ Не удалён: пользователь уже отсутствует.")

    # Return to the refreshed list so the super admin can continue.
    await _show_user_list(message, state, role)


async def handle_wrong_delete_user_input(message: Message) -> None:
    await message.answer("Пожалуйста, используйте кнопки ниже.")
