"""Shared test setup: every test runs on a SQLite file of its own and none can reach a real database.

.env may set DATABASE_URL to the production database (Postgres on Neon). In tests it never takes effect:
- DATABASE_URL is set here, before the app first reads .env, and app.config keeps a variable that is already set;
- the database_url fixture points the app, Alembic and any new Settings at a SQLite file in the test's own folder;
- a test that opens an engine on anything but SQLite, or an asyncpg connection, fails. Tests of how Postgres URLs are
  handled use offline_postgres, which records connection attempts and refuses them.

The app serves a stand-in for the React build (the web_build fixture), so tests never depend on npm run build.
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

import asyncpg
import pytest
import sqlalchemy.ext.asyncio
import sqlalchemy.ext.asyncio.engine
from sqlalchemy import make_url

if any(name == "app" or name.startswith("app.") for name in sys.modules):
    raise RuntimeError("The app was imported before tests/conftest.py, so .env's DATABASE_URL may have taken effect")
os.environ["DATABASE_URL"] = "sqlite://"  # in memory; each test's database_url fixture gives it a file of its own

REAL_ENGINE = sqlalchemy.ext.asyncio.create_async_engine
OFFLINE = {"postgres": False}  # True while offline_postgres has asyncpg stubbed out
REFUSAL = "Tests use SQLite only, the file from the database_url fixture (tests/conftest.py)"


def sqlite_engine(url, **options):
    """create_async_engine for tests: SQLite only, unless asyncpg is stubbed out."""
    backend = make_url(url).get_backend_name()
    if backend != "sqlite" and not OFFLINE["postgres"]:
        pytest.fail(f"A test opened a {backend} database. {REFUSAL}.")
    return REAL_ENGINE(url, **options)


async def refuse_connection(*args, **options):
    pytest.fail(f"A test tried to connect to Postgres. {REFUSAL}.")


# Installed before anything imports the app, so app.db and Alembic's env.py only ever get these.
sqlalchemy.ext.asyncio.create_async_engine = sqlalchemy.ext.asyncio.engine.create_async_engine = sqlite_engine
asyncpg.connect = asyncpg.connection.connect = refuse_connection


@pytest.fixture(autouse=True)
def database_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """This test's database: a SQLite file in its own folder, for the app, Alembic and any new Settings()."""
    from app import config

    url = f"sqlite:///{(tmp_path / 'walkin.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    settings = replace(config.settings, database_url=url)
    for name, module in list(sys.modules.items()):
        if name == "app" or name.startswith("app."):
            for attribute, value in list(vars(module).items()):
                if isinstance(value, config.Settings):
                    monkeypatch.setattr(module, attribute, settings)
    return url


@pytest.fixture(scope="session")
def frontend_dist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A stand-in for the React build (npm run build in frontend/): an index.html and one asset. It sits outside every
    test's own folder, which some tests use as a cache and expect empty."""
    dist = tmp_path_factory.mktemp("dist")
    (dist / "index.html").write_text("<!doctype html><title>Walk-in</title><div id=root></div>", encoding="utf-8")
    (dist / "app.js").write_text('document.title = "Walk-in";\n', encoding="utf-8")
    return dist


@pytest.fixture(autouse=True)
def web_build(frontend_dist: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The build the app serves (app.main.WEB_ROOT), the same whether or not frontend/dist exists."""
    from app import main

    monkeypatch.setattr(main, "WEB_ROOT", frontend_dist)
    return frontend_dist


@pytest.fixture
def offline_postgres(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """For tests of how Postgres URLs reach asyncpg: Postgres engines may be built, and every connection attempt is
    recorded, then refused, so none can reach a server."""
    attempts: list[dict] = []

    async def connect(*args, **options):
        attempts.append(options)
        raise ConnectionRefusedError("Tests never connect to Postgres")

    monkeypatch.setitem(OFFLINE, "postgres", True)
    monkeypatch.setattr(asyncpg, "connect", connect)
    monkeypatch.setattr(asyncpg.connection, "connect", connect)
    return attempts
