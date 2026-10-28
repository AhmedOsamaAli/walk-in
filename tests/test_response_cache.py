"""Finished surveys and ready kits served from memory (app.response_cache), and the examples loaded into it as the
server starts: no database query and no JSON work once they are in, the same bytes as before, never a running survey or
an unfinished kit, nothing deleted kept, and the warm-up never in the way of startup or the health check."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app import cache_policy
from app.db import SurveyStore
from app.response_cache import Page, ResponseCache
from app.routes import examples as examples_route
from app.routes.kits import page_body
from app.routes.surveys import RunRecord, record_body
from app.survey.models import EventLog
from tests.account_fakes import configure, dev_sign_in, make_client, run_survey
from tests.test_kits_api import FakeTiles, kit_without_streets, make_kit, wait_for


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def entry(survey: str, size: int) -> Page:
    return Page(b"x" * size, survey, "complete")


def test_the_least_recently_opened_leave_first_and_the_examples_stay(monkeypatch):
    configure(monkeypatch, examples=("example",))
    cache = ResponseCache(budget=10)
    cache.put("run:a", entry("a", 4))
    cache.put("run:b", entry("b", 4))
    cache.put("kit:pinned", entry("example", 50))  # an example's: kept whatever its size
    assert cache.get("run:a") is not None  # a is now the most recently opened
    cache.put("run:c", entry("c", 4))  # over budget: b leaves
    assert cache.get("run:b") is None and cache.get("run:a") and cache.get("run:c") and cache.get("kit:pinned")
    cache.put("run:huge", entry("huge", 11))  # larger than the whole budget: not kept, nothing else lost
    assert cache.get("run:huge") is None and cache.get("run:a") and cache.get("run:c")
    cache.put("run:a", entry("a", 2))  # replaced, not counted twice
    assert cache.stats() == {"pinned": 1, "recent": 2, "bytes": 56, "hits": 6, "misses": 2}


def test_deleting_a_survey_drops_its_record_and_its_kits(monkeypatch):
    configure(monkeypatch, examples=("a",))
    cache = ResponseCache()
    cache.put("run:a", entry("a", 1))
    cache.put("kit:t1", entry("a", 1))
    cache.put("run:b", entry("b", 1))
    cache.forget_survey("a")
    assert [cache.get(key) is not None for key in ("run:a", "kit:t1", "run:b")] == [False, False, True]


def test_a_page_is_read_once_at_a_time_and_kept_only_when_final():
    async def scenario() -> tuple[list, list, ResponseCache]:
        cache, reads, gate = ResponseCache(), [], asyncio.Event()

        async def read() -> Page:
            reads.append(1)
            await gate.wait()
            return entry("a", 3)

        async def unfinished() -> Page:
            reads.append(2)
            return Page(b"{}", "b", "running", final=False)

        waiting = [asyncio.ensure_future(cache.fetch("run:a", read)) for _ in range(3)]
        await asyncio.sleep(0)
        gate.set()
        pages = await asyncio.gather(*waiting)
        again = await cache.fetch("run:a", read)
        await cache.fetch("run:b", unfinished)
        await cache.fetch("run:b", unfinished)
        return reads, [*pages, again], cache

    reads, pages, cache = asyncio.run(scenario())
    assert reads == [1, 2, 2]  # one read for four askers; an unfinished page is read each time
    assert all(page is pages[0] for page in pages) and cache.stats()["recent"] == 1


def test_a_page_read_while_its_survey_is_deleted_is_not_kept():
    """An account deleted while one of its surveys is being read: whoever asked before gets the answer, and memory keeps
    nothing of it (else the deleted survey would be served from memory afterwards)."""
    async def scenario() -> tuple[Page | None, ResponseCache]:
        cache, gate = ResponseCache(), asyncio.Event()

        async def read() -> Page:
            await gate.wait()
            return entry("a", 3)

        reading = asyncio.ensure_future(cache.fetch("run:a", read))
        await asyncio.sleep(0)  # the read is under way
        cache.forget_survey("a")
        gate.set()
        return await reading, cache

    page, cache = asyncio.run(scenario())
    assert page is not None and page.survey_id == "a"
    assert cache.stats()["recent"] == 0 and cache.get("run:a") is None


def test_a_record_is_the_bytes_fastapi_made_of_it_before():
    """Served from memory, a record must be byte for byte what the route sent when FastAPI serialized it."""
    reference = FastAPI()
    record = {"id": "abc123", "status": "complete", "created_at": "2026-10-28T11:23:11.123456+00:00",
              "events": [["run", {"label": "Café — Zamalek", "n": 1.0, "x": [1, 2.5, None, True]}, 0.0],
                         ["done", {"seconds": 12.3, "big": 1e16, "small": 1.5e-07, "uni": "\u2009→ ü"}, 12.3]]}

    @reference.get("/runs", response_model=RunRecord)
    async def runs() -> dict:
        return record

    with TestClient(reference) as client:
        assert client.get("/runs").content == record_body(record)


def test_a_kit_page_is_the_bytes_fastapi_made_of_it_before():
    """FastAPI ran jsonable_encoder, then JSONResponse; a kit's page is JSON already, so the copy is skipped."""
    page = {"token": "t", "name": "Café — Zamalek", "index": 0, "error": None,
            "kit": {"poster": {"map": {"streets": {"box": ((30.05, 31.21), (30.07, 31.23)), "points": 2}}},
                    "scores": [1.0, 2.5, 1e16, 1.5e-07], "ok": True, "note": "\u2009→ ü"}}
    assert page_body(page) == JSONResponse(jsonable_encoder(page)).body
    unusual = {"when": datetime(2026, 10, 28, 11, 23, tzinfo=UTC), "words": {"b", "a"}}  # not JSON: encoded first
    assert page_body(unusual) == JSONResponse(jsonable_encoder(unusual)).body


def test_a_finished_survey_is_read_from_the_database_once(monkeypatch):
    with make_client() as client:
        run_id = run_survey(client)
        first = client.get(f"/api/runs/{run_id}")

        async def asleep(*args, **kwargs):
            raise AssertionError("the database was asked again")

        monkeypatch.setattr(client.app.state.surveys, "get", asleep)
        again = client.get(f"/api/runs/{run_id}")
        assert again.content == first.content and again.headers["cache-control"] == first.headers["cache-control"]
        assert again.headers["content-type"] == first.headers["content-type"] == "application/json"
        assert client.app.state.responses.stats()["recent"] == 1


def test_a_running_survey_and_an_unsettled_kit_are_never_kept():
    with make_client() as client:
        async def start_live() -> asyncio.Event:
            gate = asyncio.Event()
            client.app.state.live.start(EventLog("live00000002"), gate.wait())
            return gate

        gate = client.portal.call(start_live)
        assert client.get("/api/runs/live00000002").json()["status"] == "running"
        client.portal.call(gate.set)
        token = kit_without_streets(client)  # ready, but its street map may still come
        client.get(f"/api/kits/{token}")
        assert client.app.state.responses.stats()["recent"] == 0


def test_deleting_an_account_drops_its_surveys_from_memory():
    with make_client() as client:
        client.app.state.builder.tiles = FakeTiles()
        dev_sign_in(client)
        run_id = run_survey(client)
        token = make_kit(client, run_id)["token"]
        assert wait_for(client, token)["status"] == "ready"
        assert client.get(f"/api/runs/{run_id}").status_code == 200 and client.get(f"/api/kits/{token}").status_code == 200
        assert client.app.state.responses.stats()["recent"] == 2
        assert client.delete("/api/me").status_code == 204
        assert client.get(f"/api/runs/{run_id}").status_code == 404 and client.get(f"/api/kits/{token}").status_code == 404


def seed_example(client) -> tuple[str, str]:
    """A finished survey with a ready kit that has its street map."""
    client.app.state.builder.tiles = FakeTiles()
    run_id = run_survey(client)
    token = make_kit(client, run_id)["token"]
    assert wait_for(client, token)["status"] == "ready"
    return run_id, token


def test_the_examples_are_in_memory_once_the_server_has_started(monkeypatch, database_url):
    with make_client(database_url=database_url) as client:
        run_id, token = seed_example(client)
        before = {path: client.get(path) for path in (f"/api/runs/{run_id}", f"/api/kits/{token}")}
    configure(monkeypatch, examples=(run_id,))
    with make_client(database_url=database_url) as client:  # a restart
        state = client.app.state

        async def warmed() -> None:
            await state.warmup

        client.portal.call(warmed)
        assert state.responses.stats()["pinned"] == 2

        async def asleep(*args, **kwargs):
            raise AssertionError("an example waited for the database")

        for store, name in ((state.surveys, "get"), (state.kits, "kit"), (state.kits, "for_concept")):
            monkeypatch.setattr(store, name, asleep)
        for path, earlier in before.items():
            now = client.get(path)
            assert now.status_code == 200 and now.content == earlier.content, path
        assert client.get(f"/api/runs/{run_id}").headers["cache-control"] == cache_policy.EXAMPLE_RUN
        assert client.get(f"/api/kits/{token}").headers["cache-control"] == cache_policy.EXAMPLE_KIT
        listed = client.get("/api/examples")
        assert [e["run_id"] for e in listed.json()] == [run_id] and listed.json()[0]["kit"]["token"] == token
        assert listed.headers["cache-control"] == cache_policy.EXAMPLES


def test_the_warm_up_never_holds_back_startup_or_the_health_check(monkeypatch, database_url):
    with make_client(database_url=database_url) as client:
        run_id, _ = seed_example(client)
    configure(monkeypatch, examples=(run_id,))
    gate, reads = {"open": False}, []
    original = SurveyStore.get

    async def waking(self, *args, **kwargs):
        reads.append(args)
        while not gate["open"]:
            await asyncio.sleep(0.01)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(SurveyStore, "get", waking)
    with make_client(database_url=database_url) as client:  # started while the database still sleeps
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["ok"] and not client.app.state.warmup.done()
        assert reads  # the warm-up is waiting for the database meanwhile
        gate["open"] = True

        async def warmed() -> None:
            await client.app.state.warmup

        client.portal.call(warmed)
        assert client.app.state.responses.stats()["pinned"] == 2


def test_the_examples_list_is_read_again_in_the_background_and_kept_while_the_database_fails(monkeypatch):
    with make_client() as client:
        run_id = run_survey(client)
        configure(monkeypatch, examples=(run_id,))
        state = client.app.state
        listed = client.get("/api/examples").json()
        assert [e["run_id"] for e in listed] == [run_id]
        monkeypatch.setattr(examples_route, "FRESH_S", 0)  # old already: the next visitor is answered at once
        reads, broken = [], {"on": True}
        original = state.surveys.get

        async def failing(*args, **kwargs):
            reads.append(args)
            if broken["on"]:
                raise ConnectionError("database down")
            return await original(*args, **kwargs)

        monkeypatch.setattr(state.surveys, "get", failing)
        state.examples_cache[(run_id,)] = (0, listed, False)
        answer = client.get("/api/examples")
        assert answer.json() == listed and answer.headers["cache-control"].startswith("public")

        async def refreshed() -> None:
            await state.examples_reading[(run_id,)]

        client.portal.call(refreshed)
        assert reads  # read again in the background, and the database failed
        answer = client.get("/api/examples")
        assert answer.json() == listed and answer.headers["cache-control"].startswith("public")  # the good list stays
