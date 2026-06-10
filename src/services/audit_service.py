"""Append-only action log backed by the ``audit_log`` table.

Every auditable action becomes one row. Logging is best-effort: a failure to
write an audit entry is swallowed (and reported to the app log) so it can never
break the user-facing flow it is recording.
"""
from __future__ import annotations

from enum import Enum
import logging

from db import SessionLocal
from models import AuditLog


logger = logging.getLogger(__name__)


class AuditAction(str, Enum):
    """Auditable actions. The log is a record of data changes only - product
    searches and logins are intentionally not audited."""

    IMPORT_EXCEL = "IMPORT_EXCEL"
    ADD_PRODUCT = "ADD_PRODUCT"
    UPDATE_PRODUCT = "UPDATE_PRODUCT"
    DELETE_PRODUCT = "DELETE_PRODUCT"
    ACCESS_DENIED = "ACCESS_DENIED"
    ERROR = "ERROR"


class AuditService:
    async def log(
        self,
        action: AuditAction | str,
        *,
        telegram_id: int | None,
        user_id: int | None = None,
        details: str | None = None,
    ) -> None:
        action_value = action.value if isinstance(action, AuditAction) else str(action)
        try:
            async with SessionLocal() as session:
                session.add(
                    AuditLog(
                        user_id=user_id,
                        telegram_id=telegram_id,
                        action=action_value,
                        details=details,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception(
                "Failed to write audit log: action=%s telegram_id=%s user_id=%s",
                action_value,
                telegram_id,
                user_id,
            )
