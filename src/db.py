from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models import Base


load_dotenv()

logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://price:price@localhost:5433/price",
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Database transaction rolled back")
            raise


async def init_db(drop_existing: bool = False) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        if drop_existing:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE products ADD COLUMN IF NOT EXISTS stock integer")
        )
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_products_normalized_model "
                "ON products (normalized_model)"
            )
        )
        # users / audit_log may pre-exist from an earlier schema, in which case
        # create_all() leaves them untouched - ensure their indexes regardless.
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_telegram_id "
                "ON users (telegram_id)"
            )
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action)")
        )

    logger.info("Database schema is ready")


async def close_db() -> None:
    await engine.dispose()
