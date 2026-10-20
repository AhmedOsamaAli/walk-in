"""End-to-end tests: real HTTP app, real pipeline and scoring, fake external services."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.images import ImageGen
from app.llm import LLM
from app.main import Services, create_app
from app.ratelimit import RateLimiter
from tests.fakes import SEAFOOD_LOCAL_FAVORITES, SITE, FakeQloo, FakeWalker, StubGeocoder

RUN_PARAMS = {"lat": SITE[0], "lon": SITE[1], "label": "Test Corner, Testville", "focus": "any", "minutes": 10}


def make_client(llm: LLM | None = None, qloo: FakeQloo | None = None) -> TestClient:
    services = Services(
        qloo=qloo or FakeQloo(),
        walker=FakeWalker(),
        llm=llm or LLM("", None, "test-model"),
        images=ImageGen(),
        geocoder=StubGeocoder(),
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
        assert client.post("/api/design", json={"run_id": run_id, "index": 0}).json() == sheet  # cached

        assert client.post("/api/design", json={"run_id": "nope", "index": 0}).status_code == 404


def test_agent_mode_grounds_what_the_llm_says():
    def completion(message: dict) -> dict:
        return {"id": "x", "object": "chat.completion", "created": 0, "model": "test-model",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}]}

    def call(call_id: str, name: str, args: dict) -> dict:
        return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        if body.get("tools"):
            if not any(m.get("role") == "tool" for m in body["messages"]):
                return httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": [
                    call("c1", "inspect_gap", {"genre": "Seafood"}), call("c2", "local_taste", {}),
                ]}))
            return httpx.Response(200, json=completion({"role": "assistant", "content": None, "tool_calls": [
                call("c3", "submit_concepts", {"concepts": [
                    {"name": "Tide & Table", "genre": "Seafood", "one_liner": "Raw bar for the block",
                     "why_here": ["Seafood ranks #1 here"], "signature": ["Oysters"], "price_level": 3,
                     "inspired_by": ["Harbor Oyster Bar", "Invented Place"]},
                    {"name": "Ghost Concept", "genre": "Not A Genre", "one_liner": "x", "why_here": [], "signature": []},
                    {"name": "Little Cellar", "genre": "Wine Bar", "one_liner": "Natural wine", "why_here": [], "signature": []},
                ]}),
            ]}))
        if system.startswith("You are a retail strategy consultant"):
            return httpx.Response(200, json=completion({"role": "assistant", "content": json.dumps(
                {"concepts": [{"name": "Generic Cafe", "genre": "Cafe", "one_liner": "Coffee for everyone"}]})}))
        if system.startswith("You are Blank Space's concept designer"):
            return httpx.Response(200, json=completion({"role": "assistant", "content": json.dumps({
                "name": "Tide & Table", "tagline": "Oysters on the corner", "concept_statement": "Because locals travel.",
                "interior": {"mood": "lively", "materials": ["tile"], "lighting": "warm", "layout": "bar", "seating": "stools"},
                "offer": ["Oysters", "Crudo"], "price_level": 3, "hours": "5pm-11pm",
                "music": {"direction": "local jazz", "artists": ["Local Jazz Trio", "Invented Artist"]},
                "partners": [{"name": "Block Place 1", "why": "next door"}, {"name": "Block News", "why": "press"},
                             {"name": "Riverside Cider Co", "why": "cider pairing"}, {"name": "Invented Partner", "why": "?"}],
                "launch": "Oyster night", "image_prompt": "a raw bar",
            })}))
        return httpx.Response(500, json={"error": {"message": "unexpected request"}})

    llm = LLM("test-key", "https://llm.test/v1/", "test-model",
              http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with make_client(llm=llm) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        names = [event for event, _ in events]
        assert "error" not in names and "notice" not in names
        tools_used = [data["tool"] for event, data in events if event == "agent"]
        assert tools_used == ["inspect_gap", "local_taste"]

        concepts = first(events, "concepts")
        assert concepts["mode"] == "agent"
        assert [c["genre"] for c in concepts["concepts"]] == ["Seafood", "Wine Bar"]
        assert concepts["concepts"][0]["inspired_by"] == ["Harbor Oyster Bar"]
        assert first(events, "baseline")["concepts"][0]["name"] == "Generic Cafe"

        run_id = first(events, "run")["run_id"]
        sheet = client.post("/api/design", json={"run_id": run_id, "index": 0}).json()
        assert sheet["mode"] == "agent"
        assert sheet["music"]["artists"] == ["Local Jazz Trio"]
        assert [p["name"] for p in sheet["partners"]] == ["Block Place 1", "Riverside Cider Co"]


def test_qloo_failure_is_reported_and_the_stream_still_ends():
    with make_client(qloo=FakeQloo(fail=True)) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        names = [event for event, _ in events]
        assert "error" in names and names[-1] == "done"
        assert "401" in first(events, "error")["message"]


def test_map_and_lookup_endpoints():
    with make_client() as client:
        health = client.get("/api/health").json()
        assert health == {"ok": True, "qloo": True, "llm": False, "model": None, "image": False}
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
