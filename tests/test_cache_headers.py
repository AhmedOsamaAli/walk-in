"""Who may keep a copy of an API response (app.cache_policy): the Cache-Control table shared with the front door.

Public: the presets and public settings, the examples list, finished surveys and ready kits (the examples' for longer).
Only what belongs to no visitor may be served stale while the backend is down (stale-if-error); anyone's own survey or
kit never is, so deleting an account stops its share links within ten minutes. Everything else is no-store, and nothing
public ever sets a cookie or depends on who asks."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Request, Response

from app import auth, cache_policy
from app import kits as builders
from app.survey.models import EventLog
from tests.account_fakes import configure, dev_sign_in, make_client, run_survey
from tests.fakes import FakeQloo
from tests.test_kits_api import FakeTiles, kit_without_streets, make_kit, maps_of, wait_for

STATIC = "public, max-age=300, s-maxage=3600, stale-if-error=604800"
EXAMPLES = "public, max-age=60, s-maxage=300, stale-if-error=604800"
EXAMPLE_RUN = "public, max-age=3600, s-maxage=86400, stale-if-error=604800"
FINISHED_RUN = "public, max-age=60, s-maxage=600"
EXAMPLE_KIT = "public, max-age=600, s-maxage=86400, stale-if-error=604800"
READY_KIT = "public, max-age=60, s-maxage=600"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def cache_control(response) -> str:
    return response.headers.get("cache-control", "")


def directives(header: str) -> dict[str, str | None]:
    """A Cache-Control header's directives, by name (lower case), with their values."""
    found: dict[str, str | None] = {}
    for part in header.split(","):
        name, _, value = part.strip().partition("=")
        if name:
            found[name.lower()] = value or None
    return found


def test_the_table_is_the_contract_with_the_front_door():
    assert (cache_policy.STATIC, cache_policy.EXAMPLES) == (STATIC, EXAMPLES)
    assert (cache_policy.EXAMPLE_RUN, cache_policy.FINISHED_RUN) == (EXAMPLE_RUN, FINISHED_RUN)
    assert (cache_policy.EXAMPLE_KIT, cache_policy.READY_KIT) == (EXAMPLE_KIT, READY_KIT)
    assert cache_policy.NO_STORE == "no-store"


def test_only_what_belongs_to_no_visitor_may_be_served_stale():
    """stale-if-error (RFC 5861) lets the front door keep a copy for a week, for when the backend is down. Anyone's own
    survey or kit carries none and stays at the edge for its s-maxage at most: the privacy page promises that deleting
    an account stops its share links working within about ten minutes."""
    for shared in (STATIC, EXAMPLES, EXAMPLE_RUN, EXAMPLE_KIT):
        assert directives(shared)["stale-if-error"] == "604800", shared
    for own in (FINISHED_RUN, READY_KIT):
        found = directives(own)
        assert not any(name.startswith("stale-") for name in found), own
        assert int(found["s-maxage"]) <= 600 and int(found["max-age"]) <= 600, own


def test_presets_settings_and_the_examples_list_are_public(monkeypatch):
    with make_client() as client:
        assert cache_control(client.get("/api/presets")) == STATIC
        assert cache_control(client.get("/api/config")) == STATIC
        assert cache_control(client.get("/api/examples")) == EXAMPLES  # none configured: an empty list, all the same
        run_id = run_survey(client)
        configure(monkeypatch, examples=(run_id,))
        listed = client.get("/api/examples")
        assert [e["run_id"] for e in listed.json()] == [run_id] and cache_control(listed) == EXAMPLES


def test_an_examples_list_read_while_the_database_failed_is_kept_nowhere_else(monkeypatch):
    with make_client() as client:
        run_id = run_survey(client)
        configure(monkeypatch, examples=(run_id,))

        async def broken(*args, **kwargs):
            raise ConnectionError("database down")

        monkeypatch.setattr(client.app.state.surveys, "get", broken)
        for _ in range(2):  # read, then from the app's own short-lived copy
            response = client.get("/api/examples")
            assert response.json() == [] and cache_control(response) == "no-store"


def test_a_finished_survey_is_public_and_an_example_for_a_day(monkeypatch):
    with make_client() as client:
        run_id = run_survey(client)
        assert cache_control(client.get(f"/api/runs/{run_id}")) == FINISHED_RUN
        configure(monkeypatch, examples=(run_id,))
        assert cache_control(client.get(f"/api/runs/{run_id}")) == EXAMPLE_RUN
    with make_client(qloo=FakeQloo(fail=True)) as client:  # one that stopped on an error has finished too
        failed = client.get("/api/run", params={"lat": 40.0, "lon": -73.0, "label": "Test Corner", "minutes": 10})
        run_id = failed.text.split('"run_id": "', 1)[1][:12]
        record = client.get(f"/api/runs/{run_id}")
        assert record.json()["status"] == "failed" and cache_control(record) == FINISHED_RUN


def test_a_running_survey_and_an_unknown_one_are_never_stored():
    with make_client() as client:
        async def start_live() -> asyncio.Event:
            gate = asyncio.Event()
            client.app.state.live.start(EventLog("live00000001"), gate.wait())
            return gate

        gate = client.portal.call(start_live)
        running = client.get("/api/runs/live00000001")
        assert running.json()["status"] == "running" and cache_control(running) == "no-store"
        client.portal.call(gate.set)

        async def saved_running(run_id: str, minutes_ago: int) -> None:
            request = {"lat": 40.0, "lon": -73.0, "label": "Test Corner", "intent": "explore"}
            await client.app.state.surveys.start(run_id, request, datetime.now(UTC) - timedelta(minutes=minutes_ago))

        client.portal.call(saved_running, "elsewhere001", 2)  # running on another server, perhaps
        elsewhere = client.get("/api/runs/elsewhere001")
        assert elsewhere.json()["status"] == "running" and cache_control(elsewhere) == "no-store"
        client.portal.call(saved_running, "cutoff000001", 20)  # a restart cut it off: failed, and finished
        assert cache_control(client.get("/api/runs/cutoff000001")) == FINISHED_RUN
        missing = client.get("/api/runs/unknown")
        assert missing.status_code == 404 and cache_control(missing) == "no-store"


def test_a_survey_still_saving_its_end_is_not_public_yet():
    """Its last event is out and it says complete, but until its end is saved it lives in this process only."""
    with make_client() as client:
        async def start_saving() -> asyncio.Event:
            gate = asyncio.Event()
            client.app.state.live.start(EventLog("saving000001", status="complete"), gate.wait())
            return gate

        gate = client.portal.call(start_saving)
        saving = client.get("/api/runs/saving000001")
        assert saving.json()["status"] == "complete" and cache_control(saving) == "no-store"
        client.portal.call(gate.set)
        assert client.app.state.responses.stats()["recent"] == 0


def test_a_ready_kit_is_public_and_an_example_s_for_a_day(monkeypatch):
    with make_client() as client:
        client.app.state.builder.tiles = FakeTiles()  # kits are built with their street map
        run_id = run_survey(client)
        token = make_kit(client, run_id)["token"]
        page = wait_for(client, token)
        assert page["status"] == "ready" and maps_of(page["kit"])[0]["streets"]
        assert cache_control(client.get(f"/api/kits/{token}")) == READY_KIT
        configure(monkeypatch, examples=(run_id,))
        assert cache_control(client.get(f"/api/kits/{token}")) == EXAMPLE_KIT


def test_building_failed_unknown_and_unsettled_kits_are_never_stored(monkeypatch):
    with make_client() as client:
        run_id = run_survey(client)
        state = client.app.state
        client.portal.call(lambda: state.kits.create(run_id, 0, token="building-kit", name="Kit"))
        page = client.get("/api/kits/building-kit")
        assert page.json()["status"] == "building" and cache_control(page) == "no-store"
        client.portal.call(lambda: state.kits.finish("building-kit", error="It failed."))
        page = client.get("/api/kits/building-kit")
        assert page.json()["status"] == "failed" and cache_control(page) == "no-store"
        assert cache_control(client.get("/api/kits/no-such-kit")) == "no-store"

        # Ready, but its street map may still come: not stored until it has it.
        token = kit_without_streets(client)
        assert cache_control(client.get(f"/api/kits/{token}")) == READY_KIT  # no source of street maps: settled
        tiles = FakeTiles(fail=True)
        state.builder.tiles = tiles
        page = client.get(f"/api/kits/{token}")
        assert maps_of(page.json()["kit"])[0]["streets"] is None and cache_control(page) == "no-store"
        monkeypatch.setattr(builders, "FILL_REST_S", 0.0)
        tiles.fail = False
        page = client.get(f"/api/kits/{token}")
        assert maps_of(page.json()["kit"])[0]["streets"] and cache_control(page) == READY_KIT


def test_everything_else_is_no_store():
    with make_client() as client:
        stream = client.get("/api/run", params={"lat": 40.0, "lon": -73.0, "label": "Test Corner", "minutes": 10})
        assert stream.headers["content-type"].startswith("text/event-stream") and cache_control(stream) == "no-store"
        run_id = stream.text.split('"run_id": "', 1)[1][:12]
        answers = [
            client.get("/api/health"),
            client.get("/api/me"),
            client.get("/api/me/places"),  # 401
            client.get("/api/catchment", params={"lat": 40.0, "lon": -73.0}),
            client.get("/api/geocode", params={"q": "Main Street"}),
            client.get("/api/reverse", params={"lat": 40.0, "lon": -73.0}),
            client.get("/api/places", params={"q": "fish shack", "lat": 40.0, "lon": -73.0}),
            client.get("/api/heatmap", params={"lat": 40.0, "lon": -73.0, "tag": "urn:tag:genre:place:test_seafood"}),
            client.get("/api/kits", params={"run_id": run_id, "index": 0}),
            client.get("/api/run", params={"lat": 123}),  # 422
            client.post("/api/design", json={"run_id": run_id, "index": 0}),
            client.post("/api/kits", json={"run_id": run_id, "index": 0}),
            client.post("/api/auth/logout"),
            client.delete("/api/me"),  # 401
        ]
        for answer in answers:
            assert cache_control(answer) == "no-store", (answer.request.method, answer.request.url, answer.status_code)
        dev_sign_in(client)
        signed_in = [client.get("/api/me"), client.get("/api/me/places")]
        assert [cache_control(a) for a in signed_in] == ["no-store", "no-store"]
        assert client.get("/").headers["cache-control"] == "no-cache"  # the web app's pages keep their own


def test_a_public_answer_is_the_same_for_everyone_and_sets_no_cookie():
    with make_client() as client:
        client.app.state.builder.tiles = FakeTiles()
        run_id = run_survey(client)
        token = make_kit(client, run_id)["token"]
        wait_for(client, token)
        anonymous = {path: client.get(path) for path in (f"/api/runs/{run_id}", f"/api/kits/{token}")}
        dev_sign_in(client)  # a session cookie and a device cookie now go with every request
        assert client.cookies.get(auth.SESSION_COOKIE)
        for path, first in anonymous.items():
            again = client.get(path, headers={"X-Forwarded-For": "203.0.113.7", "X-Client-IP": "198.51.100.9"})
            assert again.content == first.content and cache_control(again).startswith("public")
            assert "set-cookie" not in again.headers and "set-cookie" not in first.headers
        client.cookies.clear()
        client.cookies.set(auth.SESSION_COOKIE, "expired-or-unknown")  # a stale cookie is not even read here
        stale = client.get(f"/api/runs/{run_id}")
        assert "set-cookie" not in stale.headers and cache_control(stale).startswith("public")


def test_the_guard_never_lets_a_cookie_a_write_or_an_error_be_public(tmp_path):
    with make_client(web_root=tmp_path / "no-build") as client:  # the API only, so the routes below are reached
        app = client.app

        @app.get("/api/test-public-with-cookie")
        async def public_with_cookie(request: Request, response: Response) -> dict:
            response.headers["Cache-Control"] = FINISHED_RUN
            auth.queue_cookie(request, auth.DEVICE_COOKIE, "0" * 32, 60)
            return {}

        @app.post("/api/test-public-write")
        async def public_write(response: Response) -> dict:
            response.headers["Cache-Control"] = FINISHED_RUN
            return {}

        @app.get("/api/test-public-error")
        async def public_error() -> Response:
            return Response(status_code=503, headers={"Cache-Control": FINISHED_RUN})

        with_cookie = client.get("/api/test-public-with-cookie")
        assert "set-cookie" in with_cookie.headers and cache_control(with_cookie) == "no-store"
        assert cache_control(client.post("/api/test-public-write")) == "no-store"
        assert cache_control(client.get("/api/test-public-error")) == "no-store"


def test_policies_by_status():
    assert cache_policy.for_run("abc", "running") == "no-store"
    assert cache_policy.for_run("abc", "complete") == cache_policy.for_run("abc", "failed") == FINISHED_RUN
    assert cache_policy.for_run("abc", "complete", settled=False) == "no-store"
    for status in ("building", "failed"):
        assert cache_policy.for_kit("abc", status) == "no-store"
    assert cache_policy.for_kit("abc", "ready", settled=False) == "no-store"
    assert cache_policy.for_kit("abc", "ready") == READY_KIT
    assert cache_policy.is_public("public, max-age=60") and not cache_policy.is_public("no-store")
    assert not cache_policy.is_public("private, max-age=60, publicity=1")
