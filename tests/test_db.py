"""Persistence: database URLs, the test-database guard, migrations, the survey store and snapshots of runs."""
from __future__ import annotations

import asyncio
import json
import os
import ssl
import subprocess
import sys
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import asyncpg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, make_url, select
from sqlalchemy.exc import IntegrityError

from app import config, main
from app.config import ROOT, Settings
from app.db import Database, SurveyStore, async_url
from app.db.tables import campaigns, designs, kits, metadata, orders
from app.images import ImageGen
from app.llm import LLM
from app.survey import design, pipeline, snapshot
from app.survey.models import RunState, RunStore, Site
from tests.fakes import OWNER_PLACE, SITE, FakeQloo, FakeWalker, StubGeocoder

# Made up, in the shape of Neon's connection strings.
NEON = (
    "postgresql://alex:AbC123dEf@ep-cool-darkness-123456.us-east-2.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
REQUEST = {"lat": SITE[0], "lon": SITE[1], "label": "Test Corner", "intent": "open", "business": "ramen"}


async def migrated(url: str) -> Database:
    database = Database(url)
    await database.migrate()
    return database


def test_a_test_only_ever_resolves_its_own_sqlite_file(database_url, tmp_path):
    """The guard: .env may name the production database, yet every way the app finds its database leads here."""
    target = make_url(database_url)
    assert target.get_backend_name() == "sqlite" and Path(target.database) == tmp_path / "walkin.db"
    resolved = {
        "environment": os.environ["DATABASE_URL"],
        "a new Settings()": Settings().database_url,
        "settings, which Alembic falls back to": config.settings.database_url,
        "create_app without a URL": main.settings.database_url,
    }
    assert resolved == dict.fromkeys(resolved, database_url)

    services = main.Services(
        qloo=FakeQloo(), walker=FakeWalker(), llm=LLM("", None, "test-model"), images=ImageGen(), geocoder=StubGeocoder(),
    )
    app = main.create_app(lambda: services)

    async def opened():
        async with app.router.lifespan_context(app):
            return app.state.db.engine.url

    opened_url = asyncio.run(opened())
    assert (opened_url.get_backend_name(), opened_url.database) == ("sqlite", target.database)


def test_a_test_that_reaches_for_postgres_fails_instead_of_connecting():
    with pytest.raises(pytest.fail.Exception, match="opened a postgresql database"):
        Database("postgresql://walkin:secret@db.invalid/walkin")
    with pytest.raises(pytest.fail.Exception, match="tried to connect to Postgres"):
        asyncio.run(asyncpg.connect("postgresql://walkin:secret@db.invalid/walkin"))


def test_sqlite_urls_get_the_async_driver_and_their_folder(tmp_path):
    path = tmp_path / "data" / "walkin.db"
    url, connect_args = async_url(f"sqlite:///{path.as_posix()}")
    assert (url.drivername, url.database, connect_args) == ("sqlite+aiosqlite", path.as_posix(), {})
    assert path.parent.is_dir() and not path.exists()
    assert async_url("sqlite://")[0].drivername == "sqlite+aiosqlite"


def test_postgres_urls_get_asyncpg_and_tls_from_sslmode():
    url, connect_args = async_url(NEON)
    assert url.drivername == "postgresql+asyncpg" and not url.query and connect_args == {"ssl": "require"}
    assert (url.username, url.password, url.database) == ("alex", "AbC123dEf", "neondb")
    assert url.host == "ep-cool-darkness-123456.us-east-2.aws.neon.tech"

    url, connect_args = async_url("postgres://walkin:p%40ss@db.example.com:5433/walkin?sslmode=verify-full&sslrootcert=system")
    assert (url.drivername, url.password, url.port, dict(url.query)) == ("postgresql+asyncpg", "p@ss", 5433, {})
    verified = connect_args["ssl"]
    assert isinstance(verified, ssl.SSLContext) and verified.check_hostname and verified.verify_mode == ssl.CERT_REQUIRED
    assert async_url("postgresql+psycopg2://walkin:pw@localhost/walkin")[1] == {}
    with pytest.raises(ValueError):
        async_url("mysql://walkin:pw@localhost/walkin")


@pytest.mark.parametrize("pooled", [False, True], ids=["direct", "pooled"])
def test_both_neon_connection_strings_reach_asyncpg_as_it_needs_them(offline_postgres, pooled):
    neon = NEON.replace("-123456.", "-123456-pooler.") if pooled else NEON
    url, connect_args = async_url(neon)
    assert connect_args == ({"ssl": "require", "statement_cache_size": 0} if pooled else {"ssl": "require"})
    assert dict(url.query) == ({"prepared_statement_cache_size": "0"} if pooled else {})

    async def connect() -> dict:
        database = Database(neon)
        try:
            with pytest.raises(ConnectionRefusedError):
                async with database.engine.connect():
                    pass
            return database.engine.dialect.create_connect_args(database.engine.url)[1]
        finally:
            await database.dispose()

    dialect_options = asyncio.run(connect())
    # PgBouncer in transaction mode (Neon's pooler) cannot keep prepared statements: both caches are off when pooled.
    assert dialect_options.get("prepared_statement_cache_size") == (0 if pooled else None)
    sent = offline_postgres[-1]
    assert (sent["host"], sent["user"], sent["database"], sent["ssl"]) == (url.host, "alex", "neondb", "require")
    assert sent.get("statement_cache_size") == (0 if pooled else None)
    assert not {"sslmode", "channel_binding", "prepared_statement_cache_size"} & set(sent)


def test_migrations_build_exactly_the_tables_the_app_uses(database_url):
    async def build() -> tuple[list, list[str]]:
        database = await migrated(database_url)
        await database.migrate()  # nothing left to do the second time
        async with database.engine.connect() as connection:
            drift = await connection.run_sync(lambda c: compare_metadata(MigrationContext.configure(c), metadata))
            tables = await connection.run_sync(lambda c: inspect(c).get_table_names())
        await database.dispose()
        return drift, tables

    drift, tables = asyncio.run(build())
    assert drift == []
    assert set(tables) == {*metadata.tables, "alembic_version"}


def test_the_alembic_command_line_migrates_the_database_it_is_given(database_url, tmp_path):
    # A separate process escapes the in-process guard, so the database is named twice: -x url and DATABASE_URL.
    assert make_url(database_url).get_backend_name() == "sqlite"
    command = [sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "-x", f"url={database_url}",
               "upgrade", "head"]
    subprocess.run(command, cwd=tmp_path, env={**os.environ, "DATABASE_URL": database_url}, check=True, capture_output=True)

    async def tables() -> list[str]:
        database = Database(database_url)
        async with database.engine.connect() as connection:
            names = await connection.run_sync(lambda c: inspect(c).get_table_names())
        await database.dispose()
        return names

    assert {"surveys", "designs", "orders", "kits", "campaigns", "pledges", "paypal_events"} <= set(asyncio.run(tables()))


def test_the_survey_store_keeps_a_survey_and_its_design_sheets(database_url):
    started = datetime.now(UTC) - timedelta(seconds=5)
    events = [["run", {"run_id": "run1"}, 0.0], ["done", {"run_id": "run1"}, 1.5]]

    async def keep() -> tuple[dict, dict, dict[int, dict]]:
        database = await migrated(database_url)
        surveys = SurveyStore(database)
        await surveys.start("run1", REQUEST, started)
        running = await surveys.get("run1")
        await surveys.finish("run1", "complete", events, {"id": "run1"})
        finished = await surveys.get("run1")
        await surveys.save_design("run1", 0, {"name": "Tide & Table"})
        await surveys.save_design("run1", 0, {"name": "A second try"})
        await surveys.save_design("run1", 2, {"name": "Slurp"})
        sheets = await surveys.get_designs("run1")
        assert await surveys.get("nope") is None and await surveys.get_designs("nope") == {}
        with pytest.raises(IntegrityError):  # SQLite enforces foreign keys too
            await surveys.save_design("nope", 0, {"name": "Orphan"})
        await database.dispose()
        return running, finished, sheets

    running, finished, sheets = asyncio.run(keep())
    assert (running["status"], running["events"], running["state"], running["request"]) == ("running", [], None, REQUEST)
    assert (running["intent"], running["label"], running["lat"], running["lon"]) == ("open", "Test Corner", *SITE)
    assert running["created_at"] == started and running["created_at"].tzinfo is UTC
    assert (finished["status"], finished["events"], finished["state"]) == ("complete", events, {"id": "run1"})
    assert finished["updated_at"] > running["updated_at"]
    assert sheets == {0: {"name": "Tide & Table"}, 2: {"name": "Slurp"}}  # the first sheet saved for a concept stays


def test_old_surveys_are_purged_unless_an_order_or_a_campaign_refers_to_them(database_url):
    long_ago, lately = datetime.now(UTC) - timedelta(days=90), datetime.now(UTC) - timedelta(days=5)
    names = ("old", "ordered", "kitted", "pledged", "recent")

    async def purge() -> tuple[int, list[str], list]:
        database = await migrated(database_url)
        surveys = SurveyStore(database)
        for run_id in names:
            await surveys.start(run_id, REQUEST, lately if run_id == "recent" else long_ago)
        await surveys.save_design("old", 0, {"name": "Gone with its survey"})
        async with database.engine.begin() as connection:
            await connection.execute(orders.insert().values(
                id="PAYPAL-ORDER-1", survey_id="ordered", idx=0, product="launch_kit", amount_cents=1900, currency="USD",
                status="COMPLETED", environment="sandbox",
            ))
            # A kit pointing at another survey than its order would break a foreign key if that survey were deleted.
            await connection.execute(kits.insert().values(
                token="kit-token", order_id="PAYPAL-ORDER-1", survey_id="kitted", idx=0, status="ready",
            ))
            await connection.execute(campaigns.insert().values(
                id="campaign1", survey_id="pledged", idx=0, owner_token_hash="0" * 64, title="Tide & Table",
                offer={"item": "Oysters"}, amount_cents=2500, currency="USD", goal_count=50,
                deadline=datetime.now(UTC) + timedelta(days=30), status="open",
            ))
        purged = await surveys.purge(60)
        kept = [run_id for run_id in names if await surveys.get(run_id)]
        async with database.engine.connect() as connection:
            sheets = (await connection.execute(select(designs))).all()
        await database.dispose()
        return purged, kept, sheets

    purged, kept, sheets = asyncio.run(purge())
    assert purged == 1 and kept == ["ordered", "kitted", "pledged", "recent"] and sheets == []


async def survey(**brief) -> RunState:
    """A run made the way the app makes one: the real pipeline over the fake Qloo world, then a design sheet."""
    q, llm = FakeQloo(), LLM("", None, "test-model")

    async def emit(event: str, data: dict) -> None:
        pass

    run = await pipeline.analyze_site(q, FakeWalker(), llm, RunStore(), Site(*SITE, "Test Corner, Testville", **brief), emit)
    if run.concepts:
        run.designs[0] = await design.design_concept(llm, ImageGen(), run, 0, q)
    return run


@pytest.mark.parametrize("brief", [
    {"notes": "no alcohol, budget prices, halal", "size_m2": 60, "kitchen": "light", "outdoor": False},
    {"intent": "open", "business": "ramen"},
    {"intent": "improve", "place_id": OWNER_PLACE["entity_id"]},
])
def test_a_run_comes_back_whole_from_its_snapshot(brief):
    async def snapshot_mid_render() -> tuple[RunState, dict]:
        run = await survey(**brief)
        run.renders[(0, "interior")] = asyncio.get_running_loop().create_future()
        run.queued.add((0, "exterior"))
        return run, snapshot.dump_run(run)

    run, data = asyncio.run(snapshot_mid_render())
    assert "renders" not in data and "queued" not in data
    restored = snapshot.load_run(json.loads(json.dumps(data, allow_nan=False)))
    assert snapshot.dump_run(restored) == data and restored.renders == {} and restored.queued == set()
    assert isinstance(restored.catchment.ring[0], tuple) and all(isinstance(index, int) for index in restored.designs)
    # Identical but for the block summary's (genre, count) pairs, which JSON keeps as lists; they are only read as JSON.
    assert restored.summary["top_genres"] == [list(pair) for pair in run.summary["top_genres"]]
    assert replace(restored, summary=run.summary, renders=run.renders, queued=run.queued) == run


def test_a_restored_run_designs_like_the_original():
    run = asyncio.run(survey())
    restored = snapshot.load_run(json.loads(json.dumps(snapshot.dump_run(run))))
    assert restored.constraints == run.constraints and restored.explored == run.explored

    def sheet(of: RunState) -> dict:
        return asyncio.run(design.design_concept(LLM("", None, "test-model"), ImageGen(), of, 1, FakeQloo()))

    assert sheet(restored) == sheet(run)


def test_an_older_snapshot_without_newer_fields_still_loads():
    run = asyncio.run(survey(intent="open", business="ramen"))
    data = snapshot.dump_run(run)
    del data["verdict"], data["site"]["place_id"]
    data["field_from_the_future"] = True
    restored = snapshot.load_run(data)
    assert restored.verdict is None and restored.site.place_id == "" and restored.concepts == run.concepts


def test_runs_come_back_from_the_database_when_memory_has_let_them_go(database_url):
    async def come_back() -> tuple[RunState, RunState | None, RunState | None, RunState | None, RunState | None]:
        run = await survey()
        database = await migrated(database_url)
        surveys = SurveyStore(database)
        await surveys.start(run.id, asdict(run.site), datetime.now(UTC))
        await surveys.finish(run.id, "complete", [], snapshot.dump_run(run))
        await surveys.save_design(run.id, 1, {"name": "Designed after the survey"})
        await surveys.start("unfinished", asdict(run.site), datetime.now(UTC))
        runs = RunStore(load=partial(snapshot.restore, surveys))
        loaded, again = await runs.fetch(run.id), await runs.fetch(run.id)
        unfinished, unknown = await runs.fetch("unfinished"), await runs.fetch("unknown")
        await database.dispose()
        return run, loaded, again, unfinished, unknown

    run, loaded, again, unfinished, unknown = asyncio.run(come_back())
    assert loaded is again  # kept in memory once loaded
    assert loaded.designs == {**run.designs, 1: {"name": "Designed after the survey"}}
    assert snapshot.dump_run(replace(loaded, designs=run.designs)) == snapshot.dump_run(run)
    assert unfinished is None and unknown is None
