"""Alembic environment: async engine, URL from DATABASE_URL or the caller."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hse_schedule import accounts, student_requests  # noqa: F401  (registers models)
from hse_schedule.db import Base, async_database_url, database_url_from_env

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.attributes.get("database_url") or database_url_from_env()
    if not url:
        raise RuntimeError("Задайте DATABASE_URL, например postgresql://user:pass@localhost/dekanat")
    return async_database_url(url)


def _configure(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_configure)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_online())
