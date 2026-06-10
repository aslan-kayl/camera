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

# The Postgres container defaults to UTC, so timestamps read back 5 hours behind
# local time. Pin the session timezone (override via TIMEZONE in .env) so every
# connection stores/returns timestamps in the user's local time.
TIMEZONE = os.getenv("TIMEZONE", "Asia/Samarkand")

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"server_settings": {"timezone": TIMEZONE}},
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
        # Make local time the database default too, so external clients (psql,
        # DBeaver) also display timestamps in the local timezone.
        dbname = await conn.scalar(text("SELECT current_database()"))
        await conn.execute(text(f'ALTER DATABASE "{dbname}" SET timezone TO \'{TIMEZONE}\''))
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
        # A pre-existing users table may carry a CHECK that predates SUPER_ADMIN;
        # relax it to the three current roles.
        await conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check"))
        await conn.execute(
            text(
                "ALTER TABLE users ADD CONSTRAINT users_role_check "
                "CHECK (role IN ('SUPER_ADMIN', 'ADMIN', 'USER'))"
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
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_invites_token ON invites (token)")
        )

    logger.info("Database schema is ready")


async def close_db() -> None:
    await engine.dispose()
