"""Centralized access control backed by the ``users`` table.

Runtime authorization reads the user's role from the database (never from an
in-code list). ``ADMIN_IDS`` from the environment is consulted only to bootstrap
the very first SUPER_ADMIN(s) at registration time - see
:func:`get_bootstrap_admin_ids`.

Role capabilities:
* SUPER_ADMIN - everything, including inviting users/admins.
* ADMIN       - mutate the catalog (Excel import, add/update/delete) and search.
* USER        - search and view only.
"""
from __future__ import annotations

import functools
import logging
import os

from aiogram.types import Message

from services.audit_service import AuditAction, AuditService
from services.user_service import ADMIN_ROLES, ROLE_SUPER_ADMIN, UserService


logger = logging.getLogger(__name__)

ADMIN_ONLY_MESSAGE = "⛔ Действие доступно только администратору."
SUPER_ADMIN_ONLY_MESSAGE = "⛔ Действие доступно только супер-администратору."

user_service = UserService()
audit_service = AuditService()


def get_bootstrap_admin_ids() -> set[int]:
    """Telegram ids seeded as SUPER_ADMIN when first registered.

    This is a convenience for the initial owner only; further admins/users are
    added via invite links. Runtime access checks always read the role from the
    ``users`` table.
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


def _require(allowed_roles, denied_message: str):
    """Build a decorator guarding a handler to the given roles.

    The role is checked against the database before the wrapped handler runs.
    A denied attempt is recorded as ``ACCESS_DENIED`` and rejected.
    """

    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(message: Message, *args, **kwargs):
            user = message.from_user
            telegram_id = user.id if user else None
            db_user = await user_service.get_by_telegram_id(telegram_id)

            if db_user is None or db_user.role not in allowed_roles:
                logger.warning(
                    "Action denied: telegram_id=%s role=%s action=%s",
                    telegram_id,
                    db_user.role if db_user else None,
                    handler.__name__,
                )
                await audit_service.log(
                    AuditAction.ACCESS_DENIED,
                    telegram_id=telegram_id,
                    user_id=db_user.id if db_user else None,
                    details=f"{handler.__name__} (requires {sorted(allowed_roles)})",
                )
                await message.answer(denied_message)
                return None

            return await handler(message, *args, **kwargs)

        return wrapper

    return decorator


# ADMIN or SUPER_ADMIN may mutate the catalog.
admin_only = _require(ADMIN_ROLES, ADMIN_ONLY_MESSAGE)
# Only SUPER_ADMIN may invite users/admins.
super_admin_only = _require({ROLE_SUPER_ADMIN}, SUPER_ADMIN_ONLY_MESSAGE)
