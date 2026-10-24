"""Finished surveys anyone can open before running their own (GET /api/examples): listed in the order configured, with
their launch kit and report, never deleted, and never in the way when the database is down."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.db import SurveyStore
from app.db.tables import surveys, utcnow
from tests.account_fakes import configure, make_client, run_survey
from tests.test_kits_api import fake_llm, make_kit, wait_for


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def test_no_examples_are_listed_until_some_are_configured():
    with make_client() as client:
        run_survey(client)
        assert client.get("/api/examples").json() == []


def test_an_example_lists_what_the_survey_found_and_links_its_kit_and_report(monkeypatch):
    asked: list[str] = []
    with make_client(llm=fake_llm(asked)) as client:
        run_id = run_survey(client, ages="25_34")
        token = make_kit(client, run_id, 1)["token"]
        assert wait_for(client, token)["status"] == "ready"
        drive = run_survey(client, travel="drive", minutes=30)
        configure(monkeypatch, examples=("nothere", run_id, "../etc", drive))

        listed = client.get("/api/examples").json()
        assert [e["run_id"] for e in listed] == [run_id, drive]  # unknown and malformed ids are left out
        walk = listed[0]
        assert walk["url"] == f"/s/{run_id}" and walk["label"] == "Test Corner, Testville"
        assert walk["intent"] == "explore" and walk["area"] == "10-minute walk" and walk["ages"] == "25–34"
        assert walk["gaps"] >= 3 and walk["top_gaps"][0] == "Seafood"
        assert walk["concepts"] and walk["headline"] == walk["concepts"][0]
        # The first concept with a ready kit: concept 0 has none, concept 1 has one.
        assert walk["kit"] == {"token": token, "index": 1, "name": walk["kit"]["name"], "url": f"/k/{token}",
                               "report_url": f"/k/{token}/dossier"}
        assert listed[1]["area"] == "30-minute drive" and listed[1]["ages"] is None and listed[1]["kit"] is None
        # Looking spends nothing: no survey is run and no kit is built.
        built = len(asked)
        client.get("/api/examples")
        assert len(asked) == built
        assert client.get("/examples").headers["content-type"].startswith("text/html")


def test_examples_are_never_deleted_with_old_surveys(monkeypatch):
    with make_client() as client:
        kept, gone = run_survey(client), run_survey(client)

        async def age_and_purge() -> int:
            engine = client.app.state.db.engine
            async with engine.begin() as connection:
                await connection.execute(update(surveys).values(created_at=utcnow() - timedelta(days=90)))
            return await SurveyStore(client.app.state.db).purge(60, keep=(kept,))

        assert client.portal.call(age_and_purge) == 1
        configure(monkeypatch, examples=(kept, gone))
        assert [e["run_id"] for e in client.get("/api/examples").json()] == [kept]


def test_a_database_failure_leaves_the_list_empty_for_now_and_the_page_working(monkeypatch):
    with make_client() as client:
        run_id = run_survey(client)
        configure(monkeypatch, examples=(run_id,))

        async def broken(*args, **kwargs):
            raise ConnectionError("database down")

        monkeypatch.setattr(client.app.state.surveys, "get", broken)
        response = client.get("/api/examples")
        assert response.status_code == 200 and response.json() == []


def test_the_list_is_kept_for_a_while_then_read_again(monkeypatch):
    from app.routes import examples as route

    with make_client() as client:
        run_id = run_survey(client)
        configure(monkeypatch, examples=(run_id,))
        assert len(client.get("/api/examples").json()) == 1
        reads = []
        original = client.app.state.surveys.get

        async def counted(*args, **kwargs):
            reads.append(args)
            return await original(*args, **kwargs)

        monkeypatch.setattr(client.app.state.surveys, "get", counted)
        client.get("/api/examples")
        assert reads == []  # served from the cache
        monkeypatch.setattr(route, "FRESH_S", 0)
        client.app.state.examples_cache.clear()
        client.get("/api/examples")
        assert len(reads) == 1


def test_example_of_reads_old_surveys_without_the_new_fields():
    from app.routes.examples import example_of

    row = {"id": "abc", "status": "complete", "label": "Old Corner", "intent": "explore", "headline": "Oyster Bar",
           "events": [["run", {"run_id": "abc", "site": {"minutes": 15}}, 0.0], ["concepts", {"concepts": [{"name": "Oyster Bar"}]}, 9.0]]}
    got = example_of(row)
    assert got["area"] == "15-minute walk" and got["ages"] is None and got["gaps"] == 0 and got["concepts"] == ["Oyster Bar"]
    assert example_of({**row, "status": "running"}) is None
    assert asyncio.iscoroutinefunction(SurveyStore.purge)
