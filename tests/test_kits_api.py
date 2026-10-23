"""The launch kit (free for now), over the HTTP app with the fake Qloo world: one kit per survey concept, built in the
background (the concept designed first when needed), its page, retries, rate limits, kits a restart cut off, My places,
and kits deleted with their survey."""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest
from sqlalchemy import select

from app.db.tables import designs, kits
from app.llm import LLM
from app.survey import kit as kit_module
from tests.account_fakes import configure, dev_sign_in, make_client, run_survey


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    return configure(monkeypatch)


def rows(client, table) -> list[dict]:
    async def read() -> list[dict]:
        async with client.app.state.db.engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(select(table))).mappings()]

    return client.portal.call(read)


def wait_for(client, token: str, timeout: float = 30.0) -> dict:
    """The kit's page once its build has ended, polled as the page does."""
    deadline = time.monotonic() + timeout
    while True:
        page = client.get(f"/api/kits/{token}").json()
        if page["status"] != "building" or time.monotonic() > deadline:
            return page
        time.sleep(0.05)


def make_kit(client, run_id: str, index: int = 0) -> dict:
    response = client.post("/api/kits", json={"run_id": run_id, "index": index})
    assert response.status_code == 200, response.text
    return response.json()


def fake_llm(requests: list[str]) -> LLM:
    """A model that answers every JSON prompt with an empty object, so the evidence rules write the words, and records
    which prompts it was asked (by their first words)."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body["messages"][0]["content"][:40])
        message = {"role": "assistant", "content": "{}"}
        return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": "test-model",
                                         "choices": [{"index": 0, "finish_reason": "stop", "message": message}]})

    return LLM("test-key", "https://llm.test/v1/", "test-model",
               http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_a_concept_s_kit_is_made_once_and_built_in_the_background():
    asked: list[str] = []
    with make_client(llm=fake_llm(asked)) as client:
        run_id = run_survey(client)
        assert client.get("/api/kits", params={"run_id": run_id, "index": 0}).json() == {"kit_url": None}
        assert rows(client, designs) == []  # nobody opened the design sheet

        made = make_kit(client, run_id)
        token = made["token"]
        assert made == {"token": token, "url": f"/k/{token}", "status": "building"} and len(token) >= 43
        page = wait_for(client, token)
        assert page == {
            "token": token, "status": "ready", "survey_id": run_id, "index": 0, "name": page["name"],
            "created_at": page["created_at"], "survey_url": f"/s/{run_id}?sheet=0", "kit": page["kit"], "error": None,
        }
        assert page["name"] and page["created_at"].endswith("Z")
        payload = page["kit"]
        assert {"concept", "claims", "copy", "poster", "links", "dossier", "rejected", "notes", "mode", "built_at"} <= set(payload)
        assert payload["dossier"]["sections"] and payload["concept"]["name"] == page["name"]
        assert any(prompt.startswith("You write the launch ads") for prompt in asked)  # the model wrote the copy

        # The concept was designed first, and its sheet kept, as POST /api/design would have.
        [sheet] = rows(client, designs)
        assert (sheet["survey_id"], sheet["idx"]) == (run_id, 0)
        assert client.post("/api/design", json={"run_id": run_id, "index": 0}).json()["name"] == sheet["sheet"]["name"]

        # One kit per concept: asking again returns it, whoever asks.
        assert make_kit(client, run_id) == {"token": token, "url": f"/k/{token}", "status": "ready"}
        assert client.get("/api/kits", params={"run_id": run_id, "index": 0}).json() == {"kit_url": f"/k/{token}"}
        other = make_kit(client, run_id, 1)
        assert other["token"] != token and wait_for(client, other["token"])["status"] == "ready"
        assert len(rows(client, kits)) == 2

        for path in (f"/k/{token}", f"/k/{token}/dossier"):  # pages of the web app
            assert client.get(path).headers["content-type"].startswith("text/html")


def test_two_requests_at_once_share_one_kit():
    with make_client() as client:
        run_id = run_survey(client)

        async def both() -> list[httpx.Response]:
            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                return await asyncio.gather(*(http.post("/api/kits", json={"run_id": run_id, "index": 0}) for _ in range(2)))

        answers = client.portal.call(both)
        assert [answer.status_code for answer in answers] == [200, 200]
        assert answers[0].json()["token"] == answers[1].json()["token"]
        assert len(rows(client, kits)) == 1
        assert wait_for(client, answers[0].json()["token"])["status"] == "ready"


def test_unknown_surveys_concepts_and_kits_are_not_found():
    with make_client() as client:
        run_id = run_survey(client)
        assert client.post("/api/kits", json={"run_id": "nope", "index": 0}).status_code == 404
        assert client.post("/api/kits", json={"run_id": run_id, "index": 9}).status_code == 404
        assert client.post("/api/kits", json={"run_id": run_id, "index": -1}).status_code == 422
        assert client.get("/api/kits/no-such-kit").status_code == 404
        assert client.post("/api/kits/no-such-kit/retry").status_code == 404
        assert client.get("/api/kits", params={"run_id": "nope", "index": 0}).json() == {"kit_url": None}
        assert rows(client, kits) == []


def test_new_kits_are_rate_limited_per_client_and_per_day():
    with make_client() as client:
        run_id = run_survey(client)
        client.app.state.kit_limiter.limit = 1
        first = make_kit(client, run_id, 0)
        limited = client.post("/api/kits", json={"run_id": run_id, "index": 1})
        assert limited.status_code == 429 and "an hour" in limited.json()["detail"]
        assert make_kit(client, run_id, 0)["token"] == first["token"]  # an existing kit is not a new build

        client.app.state.kit_limiter.limit = 100
        client.app.state.kit_budget.limit = client.app.state.kit_budget.used
        spent = client.post("/api/kits", json={"run_id": run_id, "index": 1})
        assert spent.status_code == 429 and "tomorrow" in spent.json()["detail"]
        assert len(rows(client, kits)) == 1


def test_a_kit_that_failed_is_built_again_on_request(monkeypatch):
    real, calls = kit_module.build_kit, []

    async def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the model broke")
        return await real(*args, **kwargs)

    monkeypatch.setattr(kit_module, "build_kit", flaky)
    with make_client() as client:
        run_id = run_survey(client)
        token = make_kit(client, run_id)["token"]
        failed = wait_for(client, token)
        assert failed["status"] == "failed" and failed["kit"] is None and "Try again" in failed["error"]
        assert make_kit(client, run_id)["status"] == "failed"  # asking again shows it, and does not rebuild it
        retried = client.post(f"/api/kits/{token}/retry")
        assert retried.status_code == 202 and retried.json() == {"token": token, "url": f"/k/{token}", "status": "building"}
        ready = wait_for(client, token)
        assert ready["status"] == "ready" and ready["error"] is None and ready["kit"]["dossier"]
        assert client.post(f"/api/kits/{token}/retry").status_code == 409  # only failed kits


def test_kits_a_restart_cut_off_are_built_at_the_next_start(monkeypatch):
    real, gate = kit_module.build_kit, {"open": False}

    async def slow(*args, **kwargs):
        while not gate["open"]:
            await asyncio.sleep(0.02)
        return await real(*args, **kwargs)

    monkeypatch.setattr(kit_module, "build_kit", slow)
    with make_client() as client:
        run_id = run_survey(client)
        token = make_kit(client, run_id)["token"]
        assert client.get(f"/api/kits/{token}").json()["status"] == "building"
    # The server stopped mid-build: the build was cancelled and the kit kept "building" for the next start.
    with make_client() as client:
        assert client.get(f"/api/kits/{token}").json()["status"] == "building"
        gate["open"] = True
        assert wait_for(client, token)["status"] == "ready"


def test_my_places_lists_the_kits_of_my_surveys_and_deleting_the_account_deletes_them():
    with make_client() as client:
        theirs = run_survey(client, label="Someone else's")
        their_kit = make_kit(client, theirs)
        client.cookies.clear()  # another browser
        dev_sign_in(client)
        mine = run_survey(client, label="Mine")
        kit = make_kit(client, mine)
        page = wait_for(client, kit["token"])
        listed = client.get("/api/me/places").json()["kits"]
        assert listed == [{"token": kit["token"], "survey_id": mine, "index": 0, "name": page["name"], "status": "ready",
                           "created_at": page["created_at"], "url": f"/k/{kit['token']}"}]
        wait_for(client, their_kit["token"])

        assert client.delete("/api/me").status_code == 204
        assert client.get(f"/api/kits/{kit['token']}").status_code == 404  # gone with its survey
        assert [row["token"] for row in rows(client, kits)] == [their_kit["token"]]
