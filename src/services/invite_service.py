"""One-time invite links that grant a role on first use.

A super admin creates an invite for a target role; the bot turns its token into
a ``t.me/<bot>?start=<token>`` deep link. When the invitee opens it, the token
is redeemed atomically (single-use) and the role is applied to their account.
"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import func, select, update

from db import SessionLocal
from models import Invite


logger = logging.getLogger(__name__)


class InviteService:
    async def create(self, role: str, created_by: int | None) -> Invite:
        token = secrets.token_urlsafe(16)
        async with SessionLocal() as session:
            invite = Invite(token=token, role=role, created_by=created_by)
            session.add(invite)
            await session.commit()
            await session.refresh(invite)

        logger.info(
            "Invite created: id=%s role=%s created_by=%s", invite.id, role, created_by
        )
        return invite

    async def get_valid(self, token: str) -> Invite | None:
        """Return an unused invite for ``token``, or None if missing/used."""
        if not token:
            return None
        async with SessionLocal() as session:
            invite = await session.scalar(select(Invite).where(Invite.token == token))
        if invite is None or invite.used_at is not None:
            return None
        return invite

    async def redeem(self, token: str, telegram_id: int) -> Invite | None:
        """Atomically mark the invite used and return it; None if already used."""
        async with SessionLocal() as session:
            invite = await session.scalar(select(Invite).where(Invite.token == token))
            if invite is None or invite.used_at is not None:
                return None
            result = await session.execute(
                update(Invite)
                .where(Invite.token == token, Invite.used_at.is_(None))
                .values(used_by_telegram_id=telegram_id, used_at=func.now())
            )
            await session.commit()
            if result.rowcount != 1:
                return None  # lost a race to another redemption

        logger.info(
            "Invite redeemed: token=%s role=%s telegram_id=%s",
            token,
            invite.role,
            telegram_id,
        )
        return invite
