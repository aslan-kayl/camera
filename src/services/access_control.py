"""Centralized access control backed by the ``users`` table.

Runtime authorization reads the user's role from the database (never from an
in-code list). ``ADMIN_IDS`` from the environment is consulted only to bootstrap
the very first admin(s) at registration time - see :func:`get_bootstrap_admin_ids`.
Admins may mutate the catalog (Excel import, add/update/delete); everyone else is
a USER and may only search and view.
"""
from __future__ import annotations

import functools
import logging
import os

from aiogram.types import Message

from services.audit_service import AuditAction, AuditService
from services.user_service import ROLE_ADMIN, UserService


logger = logging.getLogger(__name__)

ADMIN_ONLY_MESSAGE = "⛔ Действие доступно только администратору."

user_service = UserService()
audit_service = AuditService()


def get_bootstrap_admin_ids() -> set[int]:
    """Telegram ids seeded as ADMIN when first registered.

    This is a convenience for the initial admin only; promoting further admins
    is done in the database (``UPDATE users SET role='ADMIN' WHERE ...``).
    Runtime access checks always read the role from the ``users`` table.
    """
    ids: set[int] = set()
    for chunk in os.getenv("ADMIN_IDS", "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            logger.warning("Ignoring invalid ADMIN_IDS value: %r", chunk)
    return ids


def admin_only(handler):
    """Guard a message handler so only ADMINs reach its business logic.

    The role is checked against the database before the wrapped handler runs.
    A non-admin attempt is recorded as ``ACCESS_DENIED`` and rejected.
    """

    @functools.wraps(handler)
    async def wrapper(message: Message, *args, **kwargs):
        user = message.from_user
        telegram_id = user.id if user else None
        db_user = await user_service.get_by_telegram_id(telegram_id)

        if db_user is None or db_user.role != ROLE_ADMIN:
            logger.warning(
                "Admin action denied: telegram_id=%s action=%s",
                telegram_id,
                handler.__name__,
            )
            await audit_service.log(
                AuditAction.ACCESS_DENIED,
                telegram_id=telegram_id,
                user_id=db_user.id if db_user else None,
                details=f"admin action: {handler.__name__}",
            )
            await message.answer(ADMIN_ONLY_MESSAGE)
            return None

        return await handler(message, *args, **kwargs)

    return wrapper
