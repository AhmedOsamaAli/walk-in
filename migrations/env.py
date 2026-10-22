"""Alembic's environment: migrates DATABASE_URL, the URL given with -x url=..., or the app's database on startup."""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db.database import async_url
from app.db.tables import metadata

config = context.config
if config.config_file_name:  # the command line; inside the app, logging stays the app's
    fileConfig(config.config_file_name, disable_existing_loggers=False)

url, connect_args = async_url(
    context.get_x_argument(as_dictionary=True).get("url") or config.attributes.get("url") or settings.database_url
)


def run_migrations(connection: Connection) -> None:
    # Batch mode rebuilds a SQLite table for changes its ALTER TABLE cannot make.
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


async def migrate() -> None:
    engine = create_async_engine(url, connect_args=connect_args, poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, target_metadata=metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(migrate())
