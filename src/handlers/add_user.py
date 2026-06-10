from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from keyboards import (
    ROLE_ADMIN_CHOICE_BUTTON,
    ROLE_USER_CHOICE_BUTTON,
    add_user_role_keyboard,
    main_keyboard_for_role,
)
from models import User
from services.invite_service import InviteService
from services.user_service import ROLE_ADMIN, ROLE_SUPER_ADMIN, ROLE_USER, UserService
from states.add_user import AddUser


logger = logging.getLogger(__name__)

invite_service = InviteService()
user_service = UserService()

_ROLE_LABELS = {
    ROLE_ADMIN: "администратора",
    ROLE_USER: "обычного пользователя",
}

# Privilege ranking - an invite may never lower the invitee's current role.
_ROLE_RANK = {ROLE_USER: 1, ROLE_ADMIN: 2, ROLE_SUPER_ADMIN: 3}


def _rank(role: str | None) -> int:
    return _ROLE_RANK.get(role, 0)


async def start_add_user(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddUser.waiting_role)
    logger.info(
        "Add-user started: user_id=%s",
        message.from_user.id if message.from_user else None,
    )
    await message.answer(
        "Кого добавить?\n"
        "Выберите роль — для неё будет создана одноразовая ссылка-приглашение.",
        reply_markup=add_user_role_keyboard(),
    )


async def cancel_add_user(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Главное меню.",
        reply_markup=main_keyboard_for_role(ROLE_SUPER_ADMIN),
    )


async def choose_user_role(
    message: Message, state: FSMContext, bot: Bot, db_user: User | None = None
) -> None:
    choice = (message.text or "").strip()
    if choice == ROLE_USER_CHOICE_BUTTON:
        target_role = ROLE_USER
    elif choice == ROLE_ADMIN_CHOICE_BUTTON:
        target_role = ROLE_ADMIN
    else:
        await message.answer(
            "Выберите роль с помощью кнопок.",
            reply_markup=add_user_role_keyboard(),
        )
        return

    invite = await invite_service.create(target_role, db_user.id if db_user else None)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start={invite.token}"
    label = _ROLE_LABELS[target_role]

    await state.clear()
    logger.info(
        "Invite link issued: role=%s by_user_id=%s",
        target_role,
        db_user.id if db_user else None,
    )
    await message.answer(
        f"Ссылка для добавления роли «{label}» создана (одноразовая).\n"
        "Отправьте её человеку — после перехода по ней он получит доступ:\n\n"
        f"{link}",
        reply_markup=main_keyboard_for_role(ROLE_SUPER_ADMIN),
    )


async def handle_invite_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    db_user: User | None = None,
) -> None:
    """Handle /start <token> from an invite deep link."""
    await state.clear()
    token = (command.args or "").strip()
    telegram_id = message.from_user.id if message.from_user else None
    current_role = db_user.role if db_user else None

    invite = await invite_service.get_valid(token)
    if invite is None:
        await message.answer(
            "❌ Ссылка недействительна или уже использована.",
            reply_markup=main_keyboard_for_role(current_role),
        )
        return

    # An invite must never lower the invitee's existing privileges. A super admin
    # opening an admin/user link keeps their rights, and the link is left unused
    # so it can still be forwarded to the intended person.
    if _rank(invite.role) < _rank(current_role):
        logger.info(
            "Invite ignored (would downgrade): telegram_id=%s current=%s invite=%s",
            telegram_id,
            current_role,
            invite.role,
        )
        await message.answer(
            "Эта ссылка предназначена для другого человека — ваши текущие права выше, "
            "поэтому изменения не применены.",
            reply_markup=main_keyboard_for_role(current_role),
        )
        return

    redeemed = await invite_service.redeem(token, telegram_id)
    if redeemed is None:
        await message.answer(
            "❌ Ссылка уже использована.",
            reply_markup=main_keyboard_for_role(current_role),
        )
        return

    await user_service.set_role(telegram_id, redeemed.role)
    label = _ROLE_LABELS.get(redeemed.role, redeemed.role)
    logger.info(
        "Invite accepted: telegram_id=%s role=%s", telegram_id, redeemed.role
    )
    await message.answer(
        f"✅ Доступ предоставлен: права «{label}».\n"
        "Теперь вы можете пользоваться ботом.",
        reply_markup=main_keyboard_for_role(redeemed.role),
    )


async def handle_wrong_role_input(message: Message) -> None:
    await message.answer(
        "Выберите роль с помощью кнопок.",
        reply_markup=add_user_role_keyboard(),
    )
