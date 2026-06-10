"""User-registration gate executed before any handler.

Registered as an *outer* middleware so it runs before message filtering and
state handling. On every message it ensures a ``users`` row exists for the
sender (creating it on first contact) and injects the resolved ``db_user`` and
``role`` into the handler data. The first admin(s) are seeded from
``ADMIN_IDS``; everyone else is created as USER.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from services.access_control import get_bootstrap_admin_ids
from services.user_service import ROLE_SUPER_ADMIN, ROLE_USER, UserService


logger = logging.getLogger(__name__)

user_service = UserService()


class AccessControlMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        user = event.from_user
        if user is None:
            return await handler(event, data)

        telegram_id = user.id
        # name = Telegram first_name, falling back to username, then the id.
        name = user.first_name or user.username or str(telegram_id)
        is_bootstrap = telegram_id in get_bootstrap_admin_ids()
        seed_role = ROLE_SUPER_ADMIN if is_bootstrap else ROLE_USER

        db_user, created = await user_service.get_or_create(
            telegram_id, name, role=seed_role
        )

        # Keep the bootstrap owner a SUPER_ADMIN even if their row predates it.
        if is_bootstrap and db_user.role != ROLE_SUPER_ADMIN:
            db_user = await user_service.set_role(telegram_id, ROLE_SUPER_ADMIN)

        data["db_user"] = db_user
        data["role"] = db_user.role if db_user else ROLE_USER

        if created:
            logger.info(
                "New user registered: telegram_id=%s role=%s name=%r",
                telegram_id,
                db_user.role,
                name,
            )

        return await handler(event, data)
