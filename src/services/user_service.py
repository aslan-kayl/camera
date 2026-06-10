"""User registration and role lookup backed by the ``users`` table.

Access control reads roles from here, not from any in-code list. Users are
identified solely by ``telegram_id`` and are created lazily on first contact.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db import SessionLocal
from models import User


logger = logging.getLogger(__name__)

ROLE_ADMIN = "ADMIN"
ROLE_USER = "USER"


class UserService:
    async def get_by_telegram_id(self, telegram_id: int | None) -> User | None:
        if not telegram_id:
            return None
        async with SessionLocal() as session:
            return await session.scalar(
                select(User).where(User.telegram_id == telegram_id)
            )

    async def get_or_create(
        self,
        telegram_id: int,
        name: str | None,
        *,
        role: str = ROLE_USER,
    ) -> tuple[User, bool]:
        """Return ``(user, created)`` for ``telegram_id``, creating once.

        Lookup is by ``telegram_id`` and the unique index plus the
        IntegrityError retry guarantee no duplicate users even if two of the
        user's messages race on first contact.
        """
        async with SessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == telegram_id)
            )
            if user is not None:
                return user, False

            user = User(telegram_id=telegram_id, name=name, role=role)
            session.add(user)
            try:
                await session.commit()
            except IntegrityError:
                # A concurrent first message already created the row.
                await session.rollback()
                user = await session.scalar(
                    select(User).where(User.telegram_id == telegram_id)
                )
                return user, False

            await session.refresh(user)

        logger.info(
            "User registered: id=%s telegram_id=%s role=%s",
            user.id,
            telegram_id,
            role,
        )
        return user, True

    async def set_role(self, telegram_id: int, role: str) -> User | None:
        async with SessionLocal() as session:
            user = await session.scalar(
                select(User).where(User.telegram_id == telegram_id)
            )
            if user is None:
                return None
            user.role = role
            await session.commit()
            await session.refresh(user)

        logger.info("User role changed: telegram_id=%s role=%s", telegram_id, role)
        return user

    async def is_admin(self, telegram_id: int | None) -> bool:
        user = await self.get_by_telegram_id(telegram_id)
        return user is not None and user.role == ROLE_ADMIN
