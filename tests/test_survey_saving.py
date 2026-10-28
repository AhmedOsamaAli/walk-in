"""The database stays off a survey's way: its first events never wait for the database (Neon sleeps after five idle
minutes and its first query takes seconds), who ran it and its row are saved alongside, its end is saved once its start
is, a start the database never saved is written whole at the end, and a database that is down never stops a survey."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import pytest

from app import auth
from app.db import Database, SurveyStore
from app.db.tables import surveys as survey_table
from app.main import create_app
from tests.account_fakes import RUN_PARAMS, configure, make_client, run_survey, sse_events
from tests.test_e2e import make_services


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


class Survey:
    """A survey as a browser streams it, straight through the app: when its first event came, and everything it sent."""

    def __init__(self, app, cookie: str | None = None) -> None:
        self.app, self.cookie = app, cookie
        self.first = asyncio.Event()
        self.body = b""

    async def run(self) -> list[tuple[str, dict]]:
        ended = asyncio.Event()
        asked = False

        async def receive() -> dict:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await ended.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.body":
                self.body += message.get("body", b"")
                if b"event: run" in self.body:
                    self.first.set()
                if not message.get("more_body"):
                    ended.set()

        headers = [(b"host", b"testserver")]
        if self.cookie:
            headers.append((b"cookie", f"{auth.SESSION_COOKIE}={self.cookie}".encode()))
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/api/run", "raw_path": b"/api/run", "root_path": "", "query_string": urlencode(RUN_PARAMS).encode(),
            "headers": headers, "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
        }
        await self.app(scope, receive, send)
        return sse_events(self.body.decode())


def held(method, gate: asyncio.Event, calls: list):
    """The store method, held until `gate` opens: a database that is waking up."""
    async def waiting(*args, **kwargs):
        calls.append(args)
        await gate.wait()
        return await method(*args, **kwargs)
    return waiting


async def saved_row(database_url: str, run_id: str) -> dict | None:
    database = Database(database_url)
    try:
        return await SurveyStore(database).get(run_id, with_state=False)
    finally:
        await database.dispose()


async def signed_in_user(state) -> tuple[dict, str]:
    user = await state.accounts.sign_in("dev:owner@example.com", "owner@example.com", "Olive Owner", None)
    token = auth.new_token()
    await state.accounts.open_session(user["id"], auth.token_hash(token), state.now() + timedelta(days=30))
    return user, token


def test_a_slow_database_does_not_hold_back_the_first_events(database_url):
    app = create_app(lambda: make_services(), database_url)

    async def visit():
        async with app.router.lifespan_context(app):
            state = app.state
            user, token = await signed_in_user(state)
            session_gate, start_gate, sessions, starts = asyncio.Event(), asyncio.Event(), [], []
            state.accounts.session = held(state.accounts.session, session_gate, sessions)
            state.surveys.start = held(state.surveys.start, start_gate, starts)
            survey = Survey(app, cookie=token)
            streaming = asyncio.ensure_future(survey.run())
            await asyncio.wait_for(survey.first.wait(), 10)
            # The first event is out while the database still sleeps: neither who is signed in nor the row is known yet.
            assert sessions and not starts and not session_gate.is_set()
            session_gate.set()
            for _ in range(200):  # the lookup answers, then the row is asked for
                if starts:
                    break
                await asyncio.sleep(0.01)
            assert starts and not streaming.done()  # the row waits; the survey's end waits for it
            start_gate.set()
            events = await asyncio.wait_for(streaming, 30)
        return user, events, await saved_row(database_url, events[0][1]["run_id"])

    user, events, row = asyncio.run(visit())
    assert events[-1][0] == "done" and "error" not in [name for name, _ in events]
    assert row["status"] == "complete" and row["user_id"] == user["id"]
    assert [(name, data) for name, data, _ in row["events"]] == events  # the end was saved once the start was


def test_a_start_the_database_failed_to_save_is_written_whole_at_the_end(database_url):
    app = create_app(lambda: make_services(), database_url)

    async def visit():
        async with app.router.lifespan_context(app):
            state = app.state
            user, token = await signed_in_user(state)

            async def broken(*args, **kwargs):
                raise ConnectionError("the database is waking up")

            state.surveys.start = broken
            events = await Survey(app, cookie=token).run()
        return user, events, await saved_row(database_url, events[0][1]["run_id"])

    user, events, row = asyncio.run(visit())
    assert events[-1][0] == "done" and "error" not in [name for name, _ in events]
    assert row["status"] == "complete" and row["user_id"] == user["id"] and row["label"] == RUN_PARAMS["label"]
    assert row["request"]["label"] == RUN_PARAMS["label"] and row["intent"] == "explore" and row["device_id"]
    assert [(name, data) for name, data, _ in row["events"]] == events


def test_a_database_that_is_down_throughout_never_stops_a_survey(database_url):
    app = create_app(lambda: make_services(), database_url)

    async def visit():
        async with app.router.lifespan_context(app):
            state = app.state
            _, token = await signed_in_user(state)

            async def down(*args, **kwargs):
                raise ConnectionError("the database is down")

            state.accounts.session = state.surveys.start = state.surveys.finish = down
            events = await Survey(app, cookie=token).run()
        return events, await saved_row(database_url, events[0][1]["run_id"])

    events, row = asyncio.run(visit())
    assert events[-1][0] == "done" and {"gaps", "concepts"} <= {name for name, _ in events}
    assert row is None  # nothing could be saved, and the survey still ran to its end


def test_a_survey_deleted_while_it_ran_is_not_written_again(database_url):
    app = create_app(lambda: make_services(), database_url)

    async def visit():
        async with app.router.lifespan_context(app):
            state = app.state
            finish = state.surveys.finish

            async def deleted_meanwhile(run_id, *args, **kwargs):
                async with state.db.engine.begin() as connection:
                    await connection.execute(survey_table.delete().where(survey_table.c.id == run_id))
                await finish(run_id, *args, **kwargs)

            state.surveys.finish = deleted_meanwhile
            events = await Survey(app).run()
        return events, await saved_row(database_url, events[0][1]["run_id"])

    events, row = asyncio.run(visit())
    assert events[-1][0] == "done" and row is None  # its start was saved, so its end only updates what is left


def test_a_survey_s_state_is_saved_even_when_memory_let_it_go_before_the_save(database_url):
    """Memory keeps only the latest states (RUN_STORE_SIZE); a survey's own state is saved whatever memory dropped
    meanwhile, so its design sheets and kits can always be made later."""
    app = create_app(lambda: make_services(), database_url)

    async def visit():
        async with app.router.lifespan_context(app):
            app.state.runs.get = lambda run_id: None  # newer surveys pushed it out before its end was saved
            events = await Survey(app).run()
            return events, await app.state.surveys.get(events[0][1]["run_id"])

    events, row = asyncio.run(visit())
    assert events[-1][0] == "done" and row["status"] == "complete" and row["state"]["concepts"]


def test_memory_keeps_the_latest_survey_states_and_older_ones_come_back_from_the_database(monkeypatch):
    """A real survey's state holds 15-65 MB, so a 512 MB server keeps only the latest few; an older survey's state is
    restored from its saved snapshot when a design sheet or a kit needs it, as after a restart."""
    configure(monkeypatch, run_store_size=1)
    with make_client() as client:
        first, second = run_survey(client), run_survey(client)
        runs = client.app.state.runs
        assert runs.get(first) is None and runs.get(second) is not None
        sheet = client.post("/api/design", json={"run_id": first, "index": 0})
        assert sheet.status_code == 200 and sheet.json()["name"]
        assert runs.get(first) is not None and runs.get(second) is None


def test_the_health_check_never_touches_the_database(database_url):
    app = create_app(lambda: make_services(), database_url)

    async def check() -> int:
        async with app.router.lifespan_context(app):
            await app.state.db.engine.dispose()

            def refuse(*args, **kwargs):
                raise AssertionError("GET /api/health touched the database")

            app.state.db.engine.sync_engine.pool.connect = refuse
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.get("/api/health")
                assert response.json()["ok"] is True
                return response.status_code

    assert asyncio.run(check()) == 200
