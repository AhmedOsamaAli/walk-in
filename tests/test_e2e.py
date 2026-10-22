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
from app.ratelimit import DailyBudget, RateLimiter
from tests.fakes import SEAFOOD_LOCAL_FAVORITES, SITE, FakeImages, FakeQloo, FakeWalker, StubGeocoder

RUN_PARAMS = {"lat": SITE[0], "lon": SITE[1], "label": "Test Corner, Testville", "focus": "any", "minutes": 10}


def make_client(
    llm: LLM | None = None, qloo: FakeQloo | None = None, answers: AnswerCache | None = None, images=None,
) -> TestClient:
    services = Services(
        qloo=qloo or FakeQloo(),
        walker=FakeWalker(),
        llm=llm or LLM("", None, "test-model"),
        images=images or ImageGen(),
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
        steps = {data["step"] for event, data in events if event == "status"}
        assert steps == {"walk", "block", "demand", "taste", "gaps", "concepts"}

        catchment = first(events, "catchment")
        assert catchment["minutes"] == 10 and len(catchment["ring"]) > 10

        block = first(events, "block")
        summary = block["summary"]
        assert summary["place_count"] == 30
        # Keywords are grouped by what they say; a dish written two ways is one group, labeled by its likeliest form.
        assert summary["menu"] == [{"label": "croissant", "mentions": 60, "places": 30, "keywords": ["croissant", "great croissants"]}]
        assert [(g["label"], g["places"]) for g in summary["experience"]] == [("Outdoor seating", 30), ("Friendly staff", 22)]
        assert summary["complaints"] == [{"label": "Long waits and lines", "mentions": 40, "places": 8, "keywords": ["long wait"]}]
        assert "praise" not in summary
        classics = summary["classics"]
        assert [c["name"] for c in classics] == [f"Block Place {i}" for i in (0, 5, 10, 15, 20, 25)]
        assert classics[0]["reviews"] == 1000 and classics[0]["known_for"] == ["croissant", "outdoor seating"]
        assert "rising" not in summary and "growth" not in block["places"][0]
        assert block["places"][0]["known_for"] == ["croissant", "outdoor seating"]
        assert block["places"][0]["complaints"] == ["long waits and lines"]

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
        assert "demographics" not in taste and "crowd" not in taste
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
        # Every line is specific: numbers, named places, and what to do about the competition.
        seafood = concepts["concepts"][0]
        assert seafood["one_liner"].startswith("Seafood close to home: 1 inside the walk where a block this dense has about")
        assert seafood["why_here"][1].startswith("Only 1 seafood place inside the 10-minute walk, where a block this dense usually has about")
        assert seafood["why_here"][2].startswith("All 5 seafood places locals love more than the city does are outside the walk")
        assert "Harbor Oyster Bar" in seafood["why_here"][2]
        assert seafood["beat_competitors"].startswith("1 seafood place inside the walk; it is Seafood Nearby 0 (4.0★, $)")
        assert "Their reviews complain about long waits and lines: take bookings or run a fast counter for walk-ins." in seafood["beat_competitors"]
        assert seafood["risk"].startswith("Qloo measures taste, not foot traffic")
        assert seafood["price_level"] == 2 and seafood["price_basis"] == (
            "The seafood places locals love are $$ (median of 5); the 1 inside the walk is $."
        )
        assert by_genre["Seafood"]["reading"] == "Clear gap" and by_genre["Yoga studio"]["reading"] == "Thin data"
        assert by_genre["Seafood"]["why"] == seafood["why_here"]
        assert by_genre["Seafood"]["price"]["level"] == 2

        run_id = first(events, "run")["run_id"]
        design = client.post("/api/design", json={"run_id": run_id, "index": 0})
        assert design.status_code == 200
        sheet = design.json()
        assert sheet["mode"] == "rules"
        assert sheet["interior"]["materials"] and sheet["offer"]
        assert sheet["renders"] == {"enabled": False, "model": None}
        assert [shot["kind"] for shot in sheet["shots"]] == ["interior", "exterior"]
        partner_names = [p["name"] for p in sheet["partners"]]
        assert partner_names[-1] == "Riverside Cider Co"  # a maker, not the media brand or team that over-index more
        assert not {"Block News", "Local Sports Team"} & set(partner_names)
        # The soundtrack starts from what local seafood fans listen to, then the area's own favorites.
        # The soundtrack is the neighborhood's signature artists; the one seafood fans share comes first.
        assert sheet["music"]["artists"] == ["Local Jazz Trio", "Block Party Band"]
        assert sheet["music"]["direction"] == "Artists people within 1.5 km over-index on"
        experience = sheet["experience"]
        assert [(a["name"], a.get("since")) for a in experience["soundtrack"]] == [("Block Party Band", 2019), ("Local Jazz Trio", 1985)]
        assert "screen" not in experience and "talks" not in experience  # a seafood restaurant has no screen nights
        assert "licenses" in experience["licensing"]
        assert sheet["hours"] == "Mon–Thu 11 am–10 pm · Fri–Sat 11 am–11:30 pm · Sun 11 am–10 pm"
        assert sheet["hours_basis"] == "Typical hours of the 5 seafood places locals love that list them"
        assert {"audience", "where", "when", "claims", "channels", "cautions"} <= set(sheet["launch"])
        assert concepts["concepts"][0]["for_whom"].startswith(
            "Neighbors within a 10-minute walk who now travel a median"
        ) and "km to seafood places such as Harbor Oyster Bar and Dockside Crab" in concepts["concepts"][0]["for_whom"]
        assert sheet["price_basis"] == seafood["price_basis"]
        assert sheet["interior"]["lighting"].startswith("Daylight through the shopfront")
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
        if system.startswith("You are a concept designer"):
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
         "why_here": ["Seafood ranks #1 here"], "signature": ["Oysters", "An inviting atmosphere with outdoor seating", "Crudo flight"],
         "price_level": 3, "inspired_by": ["Harbor Oyster Bar", "Invented Place"]},
        {"name": "Ghost Concept", "genre": "Not A Genre", "one_liner": "x", "why_here": [], "signature": []},
        {"name": "Second Seafood", "genre": "seafood", "one_liner": "x", "why_here": [], "signature": []},
        {"name": "Slurp", "genre": "Ramen", "one_liner": "Ramen  the  shops next door don't serve", "why_here": [], "signature": []},
        {"name": "Corner Cellar & Co", "genre": "Wine Bar", "one_liner": "Natural wine in a cozy 40-seat room",
         "why_here": [], "signature": []},
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
            "People who love Seafood also love Riverside Cider Co, Tide Magazine; artists Sea Shanty Crew, Local Jazz Trio. "
            "Shared with this area's signature taste: Riverside Cider Co, Local Jazz Trio."
        ) in findings
        # Brunch fans rank exactly like the area at large: Qloo ignored the category, so nothing is claimed.
        assert (
            "Qloo ranks people who love Brunch like everyone near the site, so their taste says nothing specific about "
            "the category here."
        ) in findings

        concepts = first(events, "concepts")
        assert concepts["mode"] == "agent" and concepts["model"] == "test-model"
        assert [c["genre"] for c in concepts["concepts"]] == ["Seafood", "Ramen", "Wine Bar"]  # one per genre, real genres only
        assert concepts["concepts"][0]["inspired_by"] == ["Harbor Oyster Bar"]
        # Signatures are what people come for: the mood and the seats are dropped; none left means the favorites' own.
        assert concepts["concepts"][0]["signature"] == ["Oysters", "Crudo flight"]
        assert concepts["concepts"][1]["signature"] == ["House ramen special", "Croissant"]
        assert concepts["concepts"][2]["name"] == "Wine Bar, Test Corner"  # "Corner Cellar" is an existing wine bar
        # Positioning is the model's, but it knows nothing about the unit or what sits beside it: an invented seat count
        # gives way to the evidence's own line, and a competitor "next door" is only known to be nearby.
        assert concepts["concepts"][1]["one_liner"] == "Ramen the shops nearby don't serve"
        wine_line = concepts["concepts"][2]["one_liner"]
        assert "40-seat" not in wine_line and not wine_line.startswith("Natural wine")
        assert concepts["concepts"][1]["evidence"][0] == (
            "Locals rank ramen #9 among the place types they engage with; six same-size areas around rank it outside the "
            "top 50, so demand is stronger here."
        )
        # The model chooses, names and positions; every factual line is rebuilt from the measured evidence.
        rows = {row["genre"]: row for row in first(events, "gaps")["rows"]}
        tide = concepts["concepts"][0]
        assert tide["why_here"] == rows["Seafood"]["why"] and tide["why_here"] != ["Seafood ranks #1 here"]
        # A price within one level of what the places locals love charge is the model's positioning call; it is kept,
        # and the basis states the evidence it was weighed against.
        assert tide["one_liner"] == "Raw bar for the block" and tide["price_level"] == 3
        assert tide["price_basis"].startswith("The seafood places locals love are $$")
        assert tide["beat_competitors"].startswith("1 seafood place inside the walk")
        assert first(events, "baseline")["concepts"][0]["name"] == "Generic Cafe"

        run_id = first(events, "run")["run_id"]
        sheet = client.post("/api/design", json={"run_id": run_id, "index": 0}).json()
        assert sheet["mode"] == "agent" and sheet["model"] == "test-model"
        assert sheet["music"]["artists"] == ["Local Jazz Trio"]  # signature artists only: not invented, not global fans'
        assert [p["name"] for p in sheet["partners"]] == ["Block Place 1", "Riverside Cider Co"]
        # Hours come from the places locals love, not from the model; the model's launch idea gives way to the plan
        # built from the evidence.
        assert sheet["hours"] == "Mon–Thu 11 am–10 pm · Fri–Sat 11 am–11:30 pm · Sun 11 am–10 pm"
        assert isinstance(sheet["launch"], dict) and "Oyster night" not in str(sheet["launch"])
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
        assert sum(1 for e, d in events if e == "finding" and d["text"].startswith("People who love Seafood")) == 1
        last_turn = [m["content"] for m in requests[-1]["messages"] if m["role"] == "tool"]
        assert "You already ran this check" in last_turn[1]


def test_agent_live_tests_are_budgeted(monkeypatch):
    from app.survey import concepts

    monkeypatch.setattr(concepts, "MAX_LIVE_TESTS", 1)
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
        # The agent proposed one concept; the strongest measured gaps fill the other two places.
        concepts = first(events, "concepts")["concepts"]
        assert [c["genre"] for c in concepts] == ["Ramen", "Seafood", "Brunch"]
        assert concepts[0]["name"] == "Slurp" and concepts[1]["name"] == "Seafood, Test Corner"


def render(client: TestClient, run_id: str, shot: str, index: int = 0):
    return client.post("/api/render", json={"run_id": run_id, "index": index, "shot": shot})


def test_design_sheets_render_the_interior_and_the_street_view(tmp_path):
    images = FakeImages()
    with make_client(images=images, answers=AnswerCache(tmp_path)) as client:
        run_id = first(sse_events(client.get("/api/run", params=RUN_PARAMS).text), "run")["run_id"]
        assert render(client, run_id, "interior").status_code == 404  # only shots of an opened sheet can be rendered

        sheet = client.post("/api/design", json={"run_id": run_id, "index": 0}).json()
        assert sheet["renders"] == {"enabled": True, "model": "fake-image-model"}
        interior, exterior = sheet["shots"]
        assert interior["prompt"].startswith("Interior of a small street-level seafood restaurant in Test Corner, Testville.")
        assert "Industrial chic" in interior["prompt"] or "industrial chic" in interior["prompt"]
        assert 'sign above the entrance reads "Seafood"' in exterior["prompt"]  # not "Seafood, Test Corner"
        assert all("No people" in shot["prompt"] for shot in sheet["shots"])

        for shot in ("interior", "exterior"):
            assert render(client, run_id, shot).json() == {"image": FakeImages.TINY_PNG, "model": "fake-image-model"}
        assert [aspect for _, aspect in images.calls] == ["16:9", "16:9"]
        assert render(client, run_id, "interior").status_code == 200 and len(images.calls) == 2  # once per run

        rerun = first(sse_events(client.get("/api/run", params=RUN_PARAMS).text), "run")["run_id"]
        client.post("/api/design", json={"run_id": rerun, "index": 0})
        assert render(client, rerun, "exterior").json()["image"] == FakeImages.TINY_PNG
        assert len(images.calls) == 2  # and reused across runs while the prompt is unchanged

        assert render(client, run_id, "kitchen").status_code == 422


def test_renders_are_capped_per_day_and_a_failed_render_can_be_retried():
    images = FakeImages()
    with make_client(images=images) as client:
        run_id = first(sse_events(client.get("/api/run", params=RUN_PARAMS).text), "run")["run_id"]
        client.post("/api/design", json={"run_id": run_id, "index": 0})
        free_tier = httpx.Response(429, text="Quota exceeded for metric: generate_content_free_tier_requests, limit: 0",
                                   request=httpx.Request("POST", "https://images.test"))
        images.error = httpx.HTTPStatusError("429", request=free_tier.request, response=free_tier)
        failed = render(client, run_id, "interior")
        assert failed.status_code == 502 and "turn on billing" in failed.json()["detail"]
        images.error = TimeoutError("queue")
        queued = render(client, run_id, "interior")
        assert queued.status_code == 202
        assert queued.json() == {"image": None, "model": None, "queued": True, "detail": "Still waiting in the free volunteer queue."}
        client.app.state.render_budget = DailyBudget(0)
        images.error = None
        assert render(client, run_id, "interior").json()["image"] == FakeImages.TINY_PNG  # resuming is not a new render
        client.app.state.render_budget = DailyBudget(60)
        images.fail = True
        assert render(client, run_id, "exterior").json()["detail"] == "The image model could not render this right now."
        images.fail = False
        assert render(client, run_id, "interior").json()["image"] == FakeImages.TINY_PNG
        client.app.state.render_budget = DailyBudget(0)
        assert render(client, run_id, "exterior").status_code == 429


def test_renders_are_skipped_without_an_image_model():
    with make_client() as client:
        run_id = first(sse_events(client.get("/api/run", params=RUN_PARAMS).text), "run")["run_id"]
        client.post("/api/design", json={"run_id": run_id, "index": 0})
        assert render(client, run_id, "interior").json() == {"image": None, "model": None}


def test_qloo_failure_is_reported_and_the_stream_still_ends():
    with make_client(qloo=FakeQloo(fail=True)) as client:
        events = sse_events(client.get("/api/run", params=RUN_PARAMS).text)
        names = [event for event, _ in events]
        assert "error" in names and names[-1] == "done"
        assert "401" in first(events, "error")["message"]


def test_map_and_lookup_endpoints():
    with make_client() as client:
        health = client.get("/api/health").json()
        assert health == {"ok": True, "qloo": True, "llm": False, "model": None, "models": [], "resting": {},
                          "image": False, "image_model": None}
        assert len(client.get("/api/presets").json()) >= 5
        walk = client.get("/api/catchment", params={"lat": SITE[0], "lon": SITE[1], "minutes": 15}).json()
        assert walk["minutes"] == 15 and walk["radius_m"] > 1100
        cells = client.get("/api/heatmap", params={"lat": SITE[0], "lon": SITE[1], "tag": "urn:tag:genre:place:test_seafood"}).json()["cells"]
        assert len(cells) == 30 and all(0 <= c["affinity"] <= 1 for c in cells)
        assert client.get("/api/geocode", params={"q": "Main Street"}).json()[0]["lat"] == SITE[0]
        page = client.get("/")
        assert page.status_code == 200 and "Walk-in" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


@pytest.mark.parametrize("params, status", [
    ({**RUN_PARAMS, "focus": "nightclubs"}, 400),
    ({**RUN_PARAMS, "minutes": 7}, 400),
    ({**RUN_PARAMS, "lat": 123}, 422),
    ({"lat": SITE[0]}, 422),
    ({**RUN_PARAMS, "kitchen": "industrial"}, 422),
    ({**RUN_PARAMS, "size_m2": 4}, 422),
    ({**RUN_PARAMS, "outdoor": "maybe"}, 422),
    ({**RUN_PARAMS, "intent": "pivot"}, 422),
    ({**RUN_PARAMS, "intent": "open"}, 400),
    ({**RUN_PARAMS, "intent": "improve"}, 400),
    ({**RUN_PARAMS, "intent": "improve", "place_id": "../etc"}, 422),
])
def test_run_rejects_bad_input(params, status):
    with make_client() as client:
        assert client.get("/api/run", params=params).status_code == status


def test_the_unit_shapes_the_concepts_and_the_design():
    params = {**RUN_PARAMS, "size_m2": 60, "kitchen": "light", "outdoor": "false"}
    with make_client() as client:
        events = sse_events(client.get("/api/run", params=params).text)
        assert first(events, "run")["site"]["kitchen"] == "light"
        rows = {row["genre"]: row for row in first(events, "gaps")["rows"]}
        # Seafood is still the block's biggest gap, shown as such, but this unit cannot host it.
        assert rows["Seafood"]["gap_score"] == max(row["gap_score"] for row in rows.values())
        assert rows["Seafood"]["fit"]["fits"] is False
        assert rows["Seafood"]["fit"]["reason"] == "needs a full kitchen with extraction; the unit has a light-prep kitchen"
        assert rows["Wine Bar"]["fit"] == {
            "fits": True, "reason": None, "needs": "light", "capacity": {"mode": "seated", "low": 27, "high": 32},
            "capacity_text": "about 27–32 seated guests at most",
        }
        concepts = first(events, "concepts")["concepts"]
        assert [c["genre"] for c in concepts] == ["Coffee shop", "Wine Bar"]  # the only solid gaps that fit

        run_id = first(events, "run")["run_id"]
        sheet = client.post("/api/design", json={"run_id": run_id, "index": 0}).json()
        assert sheet["capacity"] == "about 27–32 seated guests at most" and "Building Code" in sheet["capacity_basis"]
        assert sheet["unit"] == {"size": "60 m² (646 ft²)", "kitchen": "a light-prep kitchen", "outdoor_space": "none"}
        assert sheet["interior"]["seating"].endswith("about 27–32 seated guests at most")
        assert "sidewalk" not in sheet["interior"]["layout"]
        assert "The room is about 60 m² (646 ft²)" in sheet["shots"][0]["prompt"]


def test_a_unit_nothing_fits_gets_an_honest_answer():
    with make_client() as client:
        events = sse_events(client.get("/api/run", params={**RUN_PARAMS, "focus": "food_drink", "kitchen": "none"}).text)
        concepts = first(events, "concepts")
        assert concepts["concepts"] == [] and concepts["mode"] == "none"
        assert concepts["note"] == "Every category the block is missing is one this unit cannot host."


def test_owner_notes_are_hard_rules():
    with make_client() as client:
        params = {**RUN_PARAMS, "notes": "no alcohol licence, about 60 m2, budget prices"}
        events = sse_events(client.get("/api/run", params=params).text)
        understood = first(events, "run")["understood"]
        assert understood == ["no alcohol", "budget prices ($–$$)", "unit of about 60 m²"]
        rows = {row["genre"]: row for row in first(events, "gaps")["rows"]}
        assert rows["Wine Bar"]["ruled_out"] == "serves alcohol"
        assert rows["Coffee shop"]["ruled_out"] is None
        assert rows["Seafood"]["fit"]["fits"] is True  # 60 m² from the notes, no kitchen limit given
        concepts = first(events, "concepts")["concepts"]
        assert "Wine Bar" not in [c["genre"] for c in concepts]
        assert all(c["price_level"] in (1, 2) for c in concepts)

        params = {**RUN_PARAMS, "intent": "open", "business": "wine bar", "notes": "halal"}
        verdict = first(sse_events(client.get("/api/run", params=params).text), "verdict")
        assert verdict["level"] == "misfit" and verdict["headline"] == "Your notes rule out Wine Bar: it serves alcohol."


def test_open_intent_judges_the_requested_business_and_designs_it_first():
    with make_client() as client:
        events = sse_events(client.get("/api/run", params={**RUN_PARAMS, "intent": "open", "business": "ramen"}).text)
        assert "verdict" in {data["step"] for event, data in events if event == "status"}
        verdict = first(events, "verdict")
        # Ramen is outside the gap table, so it is measured live on the same baseline before it is judged.
        assert verdict["found"] and verdict["genre"] == "Ramen" and verdict["row"]["source"] == "owner"
        assert verdict["row"]["nearby_count"] == 0 and verdict["of"] == 9
        assert verdict["headline"].startswith("Ramen is ") and f"#{verdict['position']} of 9" in verdict["headline"]
        assert verdict["evidence"][0].startswith("Locals rank ramen #9 among the place types they engage with")
        concepts = first(events, "concepts")["concepts"]
        assert concepts[0]["genre"] == "Ramen" and len(concepts) == 3


def test_open_intent_is_honest_when_the_business_does_not_fit_or_is_unknown():
    with make_client() as client:
        params = {**RUN_PARAMS, "intent": "open", "business": "seafood", "kitchen": "none"}
        events = sse_events(client.get("/api/run", params=params).text)
        verdict = first(events, "verdict")
        assert verdict["level"] == "misfit"
        assert verdict["headline"] == (
            "Seafood does not fit this unit: it needs a full kitchen with extraction; the unit has no kitchen."
        )
        assert "Seafood" not in [c["genre"] for c in first(events, "concepts")["concepts"]]

        events = sse_events(client.get("/api/run", params={**RUN_PARAMS, "intent": "open", "business": "submarine dealer"}).text)
        verdict = first(events, "verdict")
        assert verdict["found"] is False and verdict["headline"] == "Qloo has no storefront category matching 'submarine dealer'."
        assert len(first(events, "concepts")["concepts"]) == 3  # the survey still shows what fits


def test_improve_intent_compares_the_place_with_the_ones_locals_love():
    with make_client() as client:
        found = client.get("/api/places", params={"q": "fish shack", "lat": SITE[0], "lon": SITE[1]}).json()
        assert [p["name"] for p in found] == ["Corner Fish Shack"]  # Qloo's repeated results are merged
        assert client.get("/api/places", params={"q": "nothing like it", "lat": SITE[0], "lon": SITE[1]}).json() == []

        params = {**RUN_PARAMS, "intent": "improve", "place_id": found[0]["id"]}
        events = sse_events(client.get("/api/run", params=params).text)
        names = [event for event, _ in events]
        assert "error" not in names and "concepts" not in names and names[-1] == "done"
        assert first(events, "place")["place"]["name"] == "Corner Fish Shack"
        result = first(events, "improve")
        assert result["genre"] == "Seafood"
        comparison = result["comparison"]
        # Compared with the favorites at a similar price ($$-$$$$ for a $$$ place): three of the five.
        assert comparison["peers"] == 3 and comparison["peers_label"] == "places locals love at a similar price"
        assert comparison["known_for"] == ["fresh oysters"]
        assert comparison["complaints"] == [{"label": "Slow service", "mentions": 6, "places": 1, "keywords": ["slow service"]}]
        assert "outdoor seating" in comparison["peers_known_for"] and "fresh oysters" not in comparison["peers_known_for"]
        assert comparison["offer"]["menu"]["missing"] == [{"name": "House seafood special", "places": 3}]
        assert comparison["hours"]["place"] == {"Mon–Thu": "noon–9 pm", "Fri–Sat": "noon–9 pm", "Sun": "noon–9 pm"}
        assert set(comparison["hours"]) == {"place", "peers"}
        assert [move["title"] for move in result["moves"]] == [
            "Fix what reviews flag", "Consider house seafood special", "Stay open later Fri–Sat", "Stay open later Mon–Thu",
            "Close the rating gap", "Win back the trips", "Program for the neighborhood",
        ]
        assert result["moves"][2]["why"] == (
            "The Seafood places locals love at a similar price close around 11:30 pm; Corner Fish Shack closes at 9 pm."
        )
        assert result["moves"][1]["why"] == (
            "3 of the 3 Seafood places locals love at a similar price are known for it; Corner Fish Shack is not."
        )
        assert result["moves"][0]["why"] == "Reviews of Corner Fish Shack flag slow service."
        assert result["place"]["known_for"] == ["fresh oysters"] and result["place"]["complaints"] == ["slow service"]


def test_improve_intent_reports_a_place_qloo_does_not_know():
    with make_client() as client:
        events = sse_events(client.get("/api/run", params={**RUN_PARAMS, "intent": "improve", "place_id": "missing-id"}).text)
        assert "not on Qloo" in first(events, "error")["message"] and events[-1][0] == "done"


def test_heatmap_rejects_non_tag_input():
    with make_client() as client:
        bad = client.get("/api/heatmap", params={"lat": 1, "lon": 1, "tag": "javascript:alert(1)"})
        assert bad.status_code == 422


def test_runs_are_rate_limited_per_client():
    with make_client() as client:
        client.app.state.run_limiter = RateLimiter(1, 3600)
        assert client.get("/api/run", params=RUN_PARAMS).status_code == 200
        assert client.get("/api/run", params=RUN_PARAMS).status_code == 429
