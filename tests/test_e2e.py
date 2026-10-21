"""End-to-end tests: real HTTP app, real pipeline and scoring, fake external services."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.answers import AnswerCache
from app.images import ImageGen
from app.llm import LLM
from app.main import Services, create_app
from app.ratelimit import RateLimiter
from tests.fakes import SEAFOOD_LOCAL_FAVORITES, SITE, FakeQloo, FakeWalker, StubGeocoder

RUN_PARAMS = {"lat": SITE[0], "lon": SITE[1], "label": "Test Corner, Testville", "focus": "any", "minutes": 10}


def make_client(llm: LLM | None = None, qloo: FakeQloo | None = None, answers: AnswerCache | None = None) -> TestClient:
    services = Services(
        qloo=qloo or FakeQloo(),
        walker=FakeWalker(),
        llm=llm or LLM("", None, "test-model"),
        images=ImageGen(),
        geocoder=StubGeocoder(),
        answers=answers or AnswerCache(None),
    )
    return TestClient(create_app(lambda: services))


def sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    for chunk in text.split("\n\n"):
        name, data = None, []
        for line in chunk.splitlines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events


def first(events: list[tuple[str, dict]], name: str) -> dict:
    return next(data for event, data in events if event == name)


def test_full_survey_in_rules_mode():
    with make_client() as client:
        response = client.get("/api/run", params=RUN_PARAMS)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = sse_events(response.text)
        names = [event for event, _ in events]

        for expected in ("run", "catchment", "block", "demand", "gaps", "taste", "concepts", "done"):
            assert expected in names, f"missing {expected} event"
        assert "error" not in names
        assert names[-1] == "done"

        catchment = first(events, "catchment")
        assert catchment["minutes"] == 10 and len(catchment["ring"]) > 10

        block = first(events, "block")
        assert block["summary"]["place_count"] == 30
        assert any(key == "long wait" for key, _ in block["summary"]["complaints"])

        rows = first(events, "gaps")["rows"]
        by_genre = {row["genre"]: row for row in rows}
        assert rows[0]["genre"] == "Seafood"
        assert rows[0]["favorites_kind"] == "local" and rows[0]["leakage"] > 0.8
        assert rows[0]["relative_supply"] < 0.5 and rows[0]["lift"] > 0.5
        assert by_genre["Wine Bar"]["leakage"] < 0.3
        assert by_genre["Yoga studio"]["evidence"] == "thin"
        assert by_genre["Gift shop"]["evidence"] == "atypical"
        assert {rows[-1]["evidence"], rows[-2]["evidence"]} == {"thin", "atypical"}
        assert all(not key.startswith("_") for row in rows for key in row)

        taste = first(events, "taste")
        distinctive = [b["name"] for b in taste["distinctive_brands"]]
        assert distinctive[:4] == ["Block News", "Local Sports Team", "Riverside Cider Co", "Neighborhood Bikes"]
        assert "Civic Advocacy Org" not in [b["name"] for b in taste["brands"]] + distinctive
        assert "Global Coffee" not in distinctive

        concepts = first(events, "concepts")
        assert concepts["mode"] == "rules"
        assert len(concepts["concepts"]) == 3
        assert concepts["concepts"][0]["genre"] == "Seafood"
        assert set(concepts["concepts"][0]["inspired_by"]) <= set(SEAFOOD_LOCAL_FAVORITES)
        ok_genres = {row["genre"] for row in rows if row["evidence"] == "ok"}
        assert {c["genre"] for c in concepts["concepts"]} <= ok_genres

        run_id = first(events, "run")["run_id"]
        design = client.post("/api/design", json={"run_id": run_id, "index": 0})
        assert design.status_code == 200
        sheet = design.json()
        assert sheet["mode"] == "rules"
        assert sheet["interior"]["materials"] and sheet["offer"]
        assert sheet["image"] is None
        partner_names = [p["name"] for p in sheet["partners"]]
        assert partner_names[-1] == "Riverside Cider Co"  # a maker, not the media brand or team that over-index more
        assert not {"Block News", "Local Sports Team"} & set(partner_names)
        # The soundtrack starts from what local seafood fans listen to, then the area's own favorites.
        assert sheet["music"]["artists"][:3] == ["Sea Shanty Crew", "Local Jazz Trio", "Block Party Band"]
        assert sheet["music"]["direction"] == "What local Seafood fans also listen to"
        assert client.post("/api/design", json={"run_id": run_id, "index": 0}).json() == sheet  # cached

        assert client.post("/api/design", json={"run_id": "nope", "index": 0}).status_code == 404


def tool_call(call_id: str, name: str, args: dict) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


DESIGN_REPLY = {
    "name": "Tide & Table", "tagline": "Oysters on the corner", "concept_statement": "Because locals travel.",
    "interior": {"mood": "lively", "materials": ["tile"], "lighting": "warm", "layout": "bar", "seating": "stools"},
    "offer": ["Oysters", "Crudo"], "price_level": 3, "hours": "5pm-11pm",
    "music": {"direction": "local jazz", "artists": ["Local Jazz Trio", "Invented Artist", "Sea Shanty Crew"]},
    "partners": [{"name": "Block Place 1", "why": "next door"}, {"name": "Block News", "why": "press"},
                 {"name": "Riverside Cider Co", "why": "cider pairing"}, {"name": "Tide Magazine", "why": "press"},
                 {"name": "Invented Partner", "why": "?"}],
    "launch": "Oyster night", "image_prompt": "a raw bar",
}


def scripted_llm(agent_steps: list[list[dict]], requests: list[dict] | None = None) -> LLM:
    """An OpenAI-compatible endpoint that plays the agent's tool calls step by step and answers the JSON prompts."""
    def completion(message: dict) -> dict:
        return {"id": "x", "object": "chat.completion", "created": 0, "model": "test-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}]}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if requests is not None:
            requests.append(body)
        system = body["messages"][0]["content"]
        if body.get("tools"):
            step = sum(1 for m in body["messages"] if m.get("role") == "assistant")
            return httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": agent_steps[step]}))
        if system.startswith("You are a retail strategy consultant"):
            return httpx.Response(200, json=completion({"role": "assistant", "content": json.dumps(
                {"concepts": [{"name": "Generic Cafe", "genre": "Cafe", "one_liner": "Coffee for everyone"}]})}))
        if system.startswith("You are Blank Space's concept designer"):
            return httpx.Response(200, json=completion({"role": "assistant", "content": json.dumps(DESIGN_REPLY)}))
        return httpx.Response(500, json={"error": {"message": "unexpected request"}})

    return LLM("test-key", "https://llm.test/v1/", "test-model",
               http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def because(text: str) -> dict:
    return {"reason": text}


def test_agent_investigates_live_and_is_grounded():
    investigate = [
        tool_call("c1", "inspect_gap", {"genre": "Seafood", **because("Seafood leads the gap table")}),
        tool_call("c3", "test_category", {"category": "ramen", **because("Ramen ranks just below the table")}),
        tool_call("c4", "test_category", {"category": "board game cafe", **because("A hunch")}),
        tool_call("c5", "test_category", {"category": "art museum", **because("Museums are a taste cue")}),
        tool_call("c6", "test_category", {"category": "seafood", **because("Double-check")}),
        tool_call("c7", "fan_taste", {"category": "Seafood", **because("Fit with local taste")}),
        tool_call("c8", "fan_taste", {"category": "Brunch", **because("Fit with local taste")}),
    ]
    submit = [tool_call("c9", "submit_concepts", {"concepts": [
        {"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar for the block",
         "why_here": ["Seafood ranks #1 here"], "signature": ["Oysters"], "price_level": 3,
         "inspired_by": ["Harbor Oyster Bar", "Invented Place"]},
        {"name": "Ghost Concept", "genre": "Not A Genre", "one_liner": "x", "why_here": [], "signature": []},
        {"name": "Second Seafood", "genre": "seafood", "one_liner": "x", "why_here": [], "signature": []},
        {"name": "Slurp", "genre": "Ramen", "one_liner": "Ramen nobody nearby serves", "why_here": [], "signature": []},
        {"name": "Corner Cellar & Co", "genre": "Wine Bar", "one_liner": "Natural wine", "why_here": [], "signature": []},
    ]})]
    qloo = FakeQloo()
    with make_client(llm=scripted_llm([investigate, submit]), qloo=qloo) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        names = [event for event, _ in events]
        assert "error" not in names and "notice" not in names
        calls = [data for event, data in events if event == "agent"]
        assert [call["tool"] for call in calls] == [
            "inspect_gap", "test_category", "test_category", "test_category", "test_category", "fan_taste", "fan_taste",
        ]
        assert calls[0]["args"]["reason"] == "Seafood leads the gap table"
        thinking = [(data["step"], data["state"]) for event, data in events if event == "status" and data["step"].startswith("agent-")]
        assert thinking == [("agent-0", "running"), ("agent-0", "done"), ("agent-1", "running"), ("agent-1", "done")]

        explored = {data["row"]["genre"]: data["row"] for event, data in events if event == "explored"}
        assert set(explored) == {"Ramen", "Board Game Cafe"}  # art museum is not a storefront; seafood is already measured
        ramen, board_games = explored["Ramen"], explored["Board Game Cafe"]
        assert ramen["source"] == "agent" and ramen["demand_rank"] == 9 and ramen["ref_rank"] == 51
        assert ramen["nearby_count"] == 0 and ramen["evidence"] == "ok"
        assert board_games["demand_rank"] == 51 and board_games["ref_rank"] is None
        assert ramen["gap_score"] > board_games["gap_score"]  # locals do not rank board game cafes at all
        assert sum(1 for r in qloo.requests if r.get("path") == "/v2/tags") == 2

        findings = [data["text"] for event, data in events if event == "finding"]
        assert any("Art museum as a taste cue" in text for text in findings)
        assert any(text.startswith("Seafood is already in the gap table") for text in findings)
        assert (
            "Local fans of Seafood also love Riverside Cider Co, Tide Magazine; artists Sea Shanty Crew, Local Jazz Trio. "
            "Shared with the area's signature taste: Riverside Cider Co, Local Jazz Trio."
        ) in findings
        assert "Local fans of Brunch also love Global Coffee; artists Global Pop Star." in findings

        concepts = first(events, "concepts")
        assert concepts["mode"] == "agent" and concepts["model"] == "test-model"
        assert [c["genre"] for c in concepts["concepts"]] == ["Seafood", "Ramen", "Wine Bar"]  # one per genre, real genres only
        assert concepts["concepts"][0]["inspired_by"] == ["Harbor Oyster Bar"]
        assert concepts["concepts"][2]["name"] == "Wine Bar, Test Corner"  # "Corner Cellar" is an existing wine bar
        assert concepts["concepts"][1]["evidence"][0] == "Locals rank Ramen #9 here, versus a median outside the top 50 in same-size areas around."
        assert first(events, "baseline")["concepts"][0]["name"] == "Generic Cafe"

        run_id = first(events, "run")["run_id"]
        sheet = client.post("/api/design", json={"run_id": run_id, "index": 0}).json()
        assert sheet["mode"] == "agent" and sheet["model"] == "test-model"
        assert sheet["music"]["artists"] == ["Local Jazz Trio", "Sea Shanty Crew"]  # fan artists are allowed, invented ones not
        assert [p["name"] for p in sheet["partners"]] == ["Block Place 1", "Riverside Cider Co"]
        assert client.post("/api/design", json={"run_id": run_id, "index": 1}).json()["dna"]  # designs a tested genre


def test_identical_evidence_replays_the_agent_without_spending_ai_quota(tmp_path):
    investigate = [
        tool_call("c1", "test_category", {"category": "ramen", **because("Ramen ranks just below the table")}),
        tool_call("c2", "fan_taste", {"category": "Seafood", **because("Fit with local taste")}),
    ]
    submit = [tool_call("c3", "submit_concepts", {"concepts": [
        {"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar", "why_here": [], "signature": []},
        {"name": "Slurp", "genre": "Ramen", "one_liner": "Ramen", "why_here": [], "signature": []},
    ]})]
    requests: list[dict] = []
    with make_client(llm=scripted_llm([investigate, submit], requests), answers=AnswerCache(tmp_path)) as client:
        first_run = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        first_sheet = client.post("/api/design", json={"run_id": first(first_run, "run")["run_id"], "index": 1}).json()
        spent = len(requests)
        assert spent == 4  # two agent turns, the baseline and one design sheet

        second_run = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        second_sheet = client.post("/api/design", json={"run_id": first(second_run, "run")["run_id"], "index": 1}).json()
        assert len(requests) == spent

        assert first(second_run, "replay")["model"] == "test-model"
        concepts = first(second_run, "concepts")
        assert concepts["concepts"] == first(first_run, "concepts")["concepts"]
        assert concepts["replayed_from"] and concepts["model"] == "test-model"
        assert [d["row"]["genre"] for e, d in second_run if e == "explored"] == ["Ramen"]
        assert [d for e, d in second_run if e == "agent"] == [d for e, d in first_run if e == "agent"]
        assert first(second_run, "baseline") == first(first_run, "baseline")
        assert second_sheet == first_sheet

        other_site = {**RUN_PARAMS, "notes": "Owner wants a quiet daytime business"}
        sse_events(client.get("/api/run", params=other_site).text)
        assert len(requests) > spent  # different evidence, so the agent runs again


def test_when_every_model_is_out_of_quota_the_evidence_rules_step_in():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content)["model"])
        return httpx.Response(429, json=[{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                                    "message": "Quota exceeded: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}])

    llm = LLM("test-key", "https://llm.test/v1/", "test-model", fallback_models=["second-model"],
              http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with make_client(llm=llm) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        names = [event for event, _ in events]
        assert "error" not in names and names[-1] == "done"
        assert "out of quota" in first(events, "notice")["message"]
        assert first(events, "concepts")["mode"] == "rules" and len(first(events, "concepts")["concepts"]) == 3
        assert ("agent-0", "failed") in [(d["step"], d["state"]) for e, d in events if e == "status"]
        assert sorted(set(requests)) == ["second-model", "test-model"] and len(requests) <= 4

        tried = len(requests)
        sheet = client.post("/api/design", json={"run_id": first(events, "run")["run_id"], "index": 0}).json()
        assert sheet["mode"] == "rules" and sheet["model"] is None
        assert len(requests) == tried  # resting models are not asked again


def test_repeated_checks_reuse_the_first_result_without_new_log_lines():
    first_turn = [tool_call("c1", "fan_taste", {"category": "Seafood", **because("Fit")})]
    second_turn = [
        tool_call("c2", "fan_taste", {"category": "seafood", **because("Again")}),
        tool_call("c3", "inspect_gap", {"genre": "Seafood", **because("Details")}),
    ]
    submit = [tool_call("c4", "submit_concepts", {"concepts": [
        {"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar", "why_here": [], "signature": []},
    ]})]
    requests: list[dict] = []
    with make_client(llm=scripted_llm([first_turn, second_turn, submit], requests)) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        assert [d["tool"] for e, d in events if e == "agent"] == ["fan_taste", "inspect_gap"]
        assert sum(1 for e, d in events if e == "finding" and d["text"].startswith("Local fans of Seafood")) == 1
        last_turn = [m["content"] for m in requests[-1]["messages"] if m["role"] == "tool"]
        assert "You already ran this check" in last_turn[1]


def test_agent_live_tests_are_budgeted(monkeypatch):
    from app import agent

    monkeypatch.setattr(agent, "MAX_LIVE_TESTS", 1)
    investigate = [
        tool_call("c1", "test_category", {"category": "ramen", **because("A hunch")}),
        tool_call("c2", "test_category", {"category": "board game cafe", **because("Another hunch")}),
    ]
    submit = [tool_call("c3", "submit_concepts", {"concepts": [
        {"name": "Slurp", "genre": "Ramen", "one_liner": "Ramen", "why_here": [], "signature": []},
    ]})]
    with make_client(llm=scripted_llm([investigate, submit])) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        assert [data["row"]["genre"] for event, data in events if event == "explored"] == ["Ramen"]
        assert any("budget used" in data["text"] for event, data in events if event == "finding")
        assert [c["genre"] for c in first(events, "concepts")["concepts"]] == ["Ramen"]


def test_qloo_failure_is_reported_and_the_stream_still_ends():
    with make_client(qloo=FakeQloo(fail=True)) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        names = [event for event, _ in events]
        assert "error" in names and names[-1] == "done"
        assert "401" in first(events, "error")["message"]


def test_map_and_lookup_endpoints():
    with make_client() as client:
        health = client.get("/api/health").json()
        assert health == {"ok": True, "qloo": True, "llm": False, "model": None, "models": [], "resting": {}, "image": False}
        assert len(client.get("/api/presets").json()) >= 5
        walk = client.get("/api/catchment", params={"lat": SITE[0], "lon": SITE[1], "minutes": 15}).json()
        assert walk["minutes"] == 15 and walk["radius_m"] > 1100
        cells = client.get("/api/heatmap", params={"lat": SITE[0], "lon": SITE[1], "tag": "urn:tag:genre:place:test_seafood"}).json()["cells"]
        assert len(cells) == 30 and all(0 <= c["affinity"] <= 1 for c in cells)
        assert client.get("/api/geocode", params={"q": "Main Street"}).json()[0]["lat"] == SITE[0]
        page = client.get("/")
        assert page.status_code == 200 and "Blank Space" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


@pytest.mark.parametrize("params, status", [
    ({**RUN_PARAMS, "focus": "nightclubs"}, 400),
    ({**RUN_PARAMS, "minutes": 7}, 400),
    ({**RUN_PARAMS, "lat": 123}, 422),
    ({"lat": SITE[0]}, 422),
])
def test_run_rejects_bad_input(params, status):
    with make_client() as client:
        assert client.get("/api/run", params=params).status_code == status


def test_heatmap_rejects_non_tag_input():
    with make_client() as client:
        bad = client.get("/api/heatmap", params={"lat": 1, "lon": 1, "tag": "javascript:alert(1)"})
        assert bad.status_code == 422


def test_runs_are_rate_limited_per_client():
    with make_client() as client:
        client.app.state.run_limiter = RateLimiter(1, 3600)
        assert client.get("/api/run", params=RUN_PARAMS).status_code == 200
        assert client.get("/api/run", params=RUN_PARAMS).status_code == 429
