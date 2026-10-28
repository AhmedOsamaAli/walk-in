"""The database connection: a SQLite file by default, or Postgres (Neon's free tier, for example) from DATABASE_URL."""
from __future__ import annotations

import asyncio
import ssl
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, event, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from .. import jsonio
from ..config import ROOT

MIGRATIONS = ROOT / "migrations"


def async_url(url: str) -> tuple[URL, dict[str, Any]]:
    """The async-driver URL for a sqlite:/// or postgres(ql):// URL, and the arguments its driver connects with.

    SQLite runs on aiosqlite, and the file's folder is created. Postgres runs on asyncpg, which reads neither libpq's
    sslmode nor channel_binding (Neon's URLs carry both), so they leave the query and sslmode becomes asyncpg's ssl.
    verify-ca and verify-full check the server's certificate against the system's roots, or the file in sslrootcert.
    Neon's pooled host ("-pooler") is PgBouncer in transaction mode, where neither asyncpg nor SQLAlchemy may cache
    prepared statements.
    """
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
        return parsed.set(drivername="sqlite+aiosqlite"), {}
    if backend not in ("postgres", "postgresql"):
        raise ValueError("DATABASE_URL must be a sqlite:/// or postgresql:// URL")
    query = dict(parsed.query)
    mode = query.pop("sslmode", None)
    root_cert = query.pop("sslrootcert", None)
    query.pop("channel_binding", None)
    connect_args: dict[str, Any] = {}
    if mode in ("verify-ca", "verify-full"):
        context = ssl.create_default_context(cafile=None if root_cert in (None, "system") else root_cert)
        context.check_hostname = mode == "verify-full"
        connect_args["ssl"] = context
    elif mode:
        connect_args["ssl"] = mode  # disable, allow, prefer or require: asyncpg takes libpq's names
    if "-pooler" in (parsed.host or ""):
        connect_args["statement_cache_size"] = 0  # asyncpg's own cache
        query["prepared_statement_cache_size"] = "0"  # the cache of SQLAlchemy's asyncpg dialect, read from the URL
    return parsed.set(drivername="postgresql+asyncpg", query=query), connect_args


def _enforce_foreign_keys(connection: Any, _record: Any) -> None:
    """SQLite ignores foreign keys, ON DELETE CASCADE included, unless each connection turns them on."""
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    """The app's database: an async engine, and the migrations that bring its schema up to date."""

    def __init__(self, url: str) -> None:
        self.url = url
        target, connect_args = async_url(url)
        postgres = target.get_backend_name() == "postgresql"
        # Neon suspends an idle database and drops its connections, so each is checked before use. JSON columns (a
        # survey's events, a kit's payload: 100-200 KB each) are read with orjson, to the same values as json.
        self.engine = create_async_engine(
            target, connect_args=connect_args, pool_pre_ping=postgres, json_deserializer=jsonio.loads,
        )
        if not postgres:
            event.listen(self.engine.sync_engine, "connect", _enforce_foreign_keys)

    async def migrate(self) -> None:
        """Runs `alembic upgrade head`. Its env.py starts an event loop of its own, so it runs in a worker thread."""
        config = Config()
        config.set_main_option("script_location", str(MIGRATIONS))
        config.attributes["url"] = self.url
        await asyncio.to_thread(command.upgrade, config, "head")

    async def dispose(self) -> None:
        await self.engine.dispose()
