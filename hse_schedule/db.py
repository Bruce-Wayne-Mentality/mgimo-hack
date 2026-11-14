"""Database engine, declarative base and portable column types.

Production runs on PostgreSQL 16 (asyncpg). Tests and quick local runs may use
SQLite (aiosqlite); column types below behave the same on both.
"""

from __future__ import annotations

import os
import secrets
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, MetaData
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator):
    """timestamptz in UTC; SQLite values come back timezone-aware as well."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Время должно содержать часовой пояс.")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


JSONType = JSON().with_variant(JSONB(), "postgresql")


def uuid7() -> uuid.UUID:
    """Time-ordered UUID v7 (RFC 9562) so primary-key indexes grow sequentially."""
    milliseconds = time.time_ns() // 1_000_000
    value = (milliseconds & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return uuid.UUID(int=value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def async_database_url(url: str) -> str:
    """Accept the usual postgresql:// form and pick the async driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix):]
    if url.startswith("sqlite:///"):
        return "sqlite+aiosqlite:///" + url[len("sqlite:///"):]
    return url


def database_url_from_env() -> str | None:
    value = os.environ.get("DATABASE_URL", "").strip()
    return value or None


class Database:
    """Async engine plus a session factory shared by the API and CLI commands."""

    def __init__(self, url: str, *, pooled: bool = True, echo: bool = False) -> None:
        self.url = async_database_url(url)
        options: dict = {"echo": echo}
        if not pooled or self.url.startswith("sqlite"):
            # No pooling: connections never outlive the event loop that opened
            # them (tests and CLI commands each run their own loop).
            options["poolclass"] = NullPool
        else:
            options["pool_pre_ping"] = True
        self.engine: AsyncEngine = create_async_engine(self.url, **options)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def create_all(self) -> None:
        """Test helper; production schema comes from Alembic migrations."""
        from . import accounts, student_requests  # noqa: F401  (registers models)

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()
