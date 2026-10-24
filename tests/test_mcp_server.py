"""The Walk-in MCP server (mcp_server/walkin_mcp.py) against a fake Walk-in API on httpx.MockTransport: no network."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_server import walkin_mcp
from mcp_server.walkin_mcp import CREDIT, TOO_MANY_SURVEYS, Walkin, WalkinError, read_events, summarize

BASE = "https://walkin.test"
OSM_NOTICE = "OpenStreetMap did not answer in time, so the gaps rest on Qloo's places alone and say they were not cross-checked."


def gap(genre: str, reading: str, *why: str) -> dict:
    """A gap row shaped as the `gaps` event streams it."""
    return {
        "genre_id": f"urn:tag:genre:place:{genre.lower().replace(' ', '_')}", "genre": genre, "demand_rank": 2,
        "ref_rank": 5.0, "nearby_count": 1, "nearby_capped": False, "relative_supply": 0.4, "gap_score": 80,
        "evidence": "ok", "reading": reading, "why": list(why), "osm": None,
    }


GAPS = [
    gap("Bakery", "Clear gap",
        "People here aged 25–34 rank bakery #2 among the place types they engage with; six same-size areas around rank it #9, so demand is stronger here.",
        "Only 1 bakery inside the 10-minute walk, where a block this dense usually has about 4.2."),
    gap("Wine bar", "Under-supplied", "Only 2 wine bars inside the 10-minute walk, where a block this dense usually has about 5."),
    gap("Live music venue", "People here travel for it",
        "All 4 live music venues people here love more than the rest of the city does are outside the walk, a median 6.2 km away."),
    gap("Ramen restaurant", "Loved more here", "People here rank ramen #4; the areas around rank it #11."),
    gap("Bookstore", "Thin data", "Thin evidence: Qloo knows at most one bookstore in the surrounding area."),
    gap("Pilates studio", "Steady demand", "People here rank pilates #9, about as high as the areas around (#8)."),
]
CONCEPTS = {
    "concepts": [
        {"name": "Crumb Theory", "genre": "Bakery", "gap_score": 81, "one_liner": "A neighborhood bakery for the morning crowd."},
        {"name": "Cellar Door", "genre": "Wine bar", "gap_score": 74, "one_liner": "A small natural-wine bar."},
        {"name": "Low End", "genre": "Live music venue", "gap_score": 70, "one_liner": "A 60-seat room for local bands."},
        {"name": "Dough & Disc", "genre": "Bakery", "gap_score": None, "wildcard": True,
         "one_liner": "A bakery and a record shop in one."},
    ],
    "mode": "agent",
    "model": "some-model",
}
VERDICT = {
    "query": "Starbucks", "found": True, "genre": "Coffee shop", "genre_id": "urn:tag:genre:place:restaurant:coffee_shop",
    "level": "weak", "headline": "Coffee Shop is a weak gap here (#9 of 9): demand and supply here are close to what the areas around show.",
    "position": 9, "of": 9, "gap_score": 23, "evidence": ["Only 28 coffee shops inside the 10-minute walk."],
    "chain": {
        "brand": "Starbucks", "inside": 6, "around": 14, "capped": False,
        "line": "6 Starbucks locations are already inside the 10-minute walk, and 14 within a 20-minute walk.",
        "basis": "Qloo's places that carry the Starbucks brand.",
    },
}


def survey_events(
    run_id: str = "abc123def456", *, label: str = "Williamsburg, Brooklyn", intent: str = "explore", business: str = "",
    travel: str = "walk", km: float | None = None, area: str = "10-minute walk", ages: str = "all",
    ages_label: str | None = None, verdict: dict | None = None,
) -> list[tuple[str, dict]]:
    """A survey's events as app/survey/pipeline.py streams them."""
    site = {
        "lat": 40.7145, "lon": -73.958, "label": label, "focus": "any", "notes": "", "minutes": 10, "size_m2": None,
        "kitchen": None, "outdoor": None, "intent": intent, "business": business, "place_id": "", "travel": travel,
        "km": km, "ages": ages,
    }
    walk = f"Tracing a {area} over the street network"
    events = [
        ("run", {"run_id": run_id, "site": site, "llm": True, "understood": [], "area_label": area, "ages_label": ages_label}),
        ("status", {"step": "walk", "state": "running", "label": walk}),
        ("status", {"step": "walk", "state": "done", "label": walk}),
        ("catchment", {"minutes": 10, "source": "street network", "ring": [[40.71, -73.95], [40.72, -73.96], [40.71, -73.97]],
                       "area_km2": 1.557, "radius_m": 704, "travel": travel, "km": km, "label": area, "short": area}),
        ("notice", {"message": OSM_NOTICE}),
        ("status", {"step": "gaps", "state": "running", "label": "Comparing supply with the surroundings"}),
        ("gaps", {"rows": GAPS}),
    ]
    if verdict:
        events.append(("verdict", verdict))
    events += [
        ("agent", {"tool": "explore_gap", "args": {"genre": "Bakery"}}),
        ("concepts", CONCEPTS),
        ("done", {"run_id": run_id, "seconds": 54.9, "qloo_calls": 17, "cache_hits": 85, "qloo_queries": 100,
                  "data_as_of": "2026-10-22T10:18:54+00:00"}),
    ]
    return events


def sse(events: list[tuple[str, dict]]) -> str:
    """The events as Walk-in sends them, with a keep-alive comment after every second one."""
    parts = []
    for index, (name, data) in enumerate(events):
        parts.append(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")
        if index % 2:
            parts.append(": keep-alive\n\n")
    return "".join(parts)


def stream(body: str, chunk: int = 0) -> httpx.Response:
    """An event stream; with `chunk`, sent in pieces of that many bytes, which split lines, events and characters."""
    data = body.encode()
    content = data
    if chunk:
        async def pieces():
            for start in range(0, len(data), chunk):
                yield data[start:start + chunk]
        content = pieces()
    return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"}, content=content)


class FakeApi:
    """Walk-in's API as a test sets it up: one handler per path. Every request is kept."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(request.url.path)
        return handler(request) if handler else httpx.Response(404, json={"detail": "Not Found"})

    def walkin(self, **options) -> Walkin:
        return Walkin(BASE, transport=httpx.MockTransport(self), **options)


def fail(error: type[BaseException] = WalkinError, *, call) -> str:
    with pytest.raises(error) as raised:
        asyncio.run(call)
    return str(raised.value)


# ---------- Server-sent events ----------

def test_events_skip_keep_alive_comments_and_join_data_lines():
    lines = [
        ": keep-alive", "",
        "event: run", 'data: {"run_id": "a1"}', "",
        ": keep-alive", "",
        "event: status", 'data: {"step": "walk",', 'data:  "state": "running"}', "",
        "data: plain words", "",
        "event: ping", "id: 7", "retry: 3000", "",  # no data: not an event
        "event:gaps", 'data:{"rows": []}', "",  # the space after the colon is optional
        "event: done", 'data: {"run_id": "a1"}',  # the stream ends before the event does: dropped
    ]

    async def read() -> list:
        async def source():
            for line in lines:
                yield line

        async def beat() -> None:
            beats.append(len(beats) + 1)

        return [item async for item in read_events(source(), beat)]

    beats: list[int] = []
    assert asyncio.run(read()) == [
        ("run", {"run_id": "a1"}),
        ("status", {"step": "walk", "state": "running"}),
        ("message", "plain words"),
        ("gaps", {"rows": []}),
    ]
    assert beats == [1, 2]  # each keep-alive comment is a heartbeat, never an event


def test_events_read_over_http_survive_split_chunks_and_crlf():
    body = (
        ": keep-alive\r\n\r\n"
        'event: run\r\ndata: {"run_id": "a1", "ages_label": "25–34"}\r\n\r\n'
        ": keep-alive\r\n\r\n"
        'event: done\r\ndata: {"run_id": "a1"}\r\n\r\n'
    )

    async def read(chunk: int) -> list:
        transport = httpx.MockTransport(lambda request: stream(body, chunk))
        async with httpx.AsyncClient(transport=transport) as http, http.stream("GET", f"{BASE}/api/run") as response:
            return [item async for item in read_events(response.aiter_lines())]

    expected = [("run", {"run_id": "a1", "ages_label": "25–34"}), ("done", {"run_id": "a1"})]
    for chunk in (0, 1, 3, 7):
        assert asyncio.run(read(chunk)) == expected


# ---------- survey_storefront ----------

def test_survey_geocodes_the_place_then_runs_it():
    hits = [
        {"label": "Williamsburg, Brooklyn, Kings County, New York, United States", "lat": 40.7145, "lon": -73.958},
        {"label": "Williamsburg, James City County, Virginia, United States", "lat": 37.27, "lon": -76.71},
    ]
    api = FakeApi({
        "/api/geocode": lambda request: httpx.Response(200, json=hits),
        "/api/run": lambda request: stream(sse(survey_events(ages="25_34", ages_label="25–34")), chunk=7),
    })
    progress: list[str | None] = []

    async def notify(message: str | None = None) -> None:
        progress.append(message)

    summary = asyncio.run(api.walkin().survey(place=" Williamsburg Brooklyn ", ages="25_34", progress=notify))

    geocode, run = api.requests
    assert (geocode.url.path, dict(geocode.url.params)) == ("/api/geocode", {"q": "Williamsburg Brooklyn"})
    assert run.url.path == "/api/run" and run.headers["accept"] == "text/event-stream"
    assert dict(run.url.params) == {
        "lat": "40.714500", "lon": "-73.958000", "label": "Williamsburg, Brooklyn", "travel": "walk", "minutes": "10",
        "ages": "25_34", "intent": "explore",
    }
    assert summary.splitlines()[:3] == [
        "## Walk-in survey: Williamsburg, Brooklyn",
        "- Area: 10-minute walk (1.56 km², traced over the street network)",
        "- Age focus: 25–34",
    ]
    assert "**Top gaps** (5 of 6 categories ranked, most missing first)" in summary
    assert "1. **Bakery**: Clear gap" in summary
    assert f"   - {GAPS[0]['why'][0]}" in summary and f"   - {GAPS[0]['why'][1]}" in summary
    assert "3. **Live music venue**: People here travel for it" in summary
    assert "5. **Bookstore**: Thin data" in summary
    assert "Pilates" not in summary  # the sixth gap
    assert "1. **Crumb Theory**: A neighborhood bakery for the morning crowd." in summary
    assert "4. **Dough & Disc** (wildcard: two loves combined, untested): A bakery and a record shop in one." in summary
    assert f"Note: {OSM_NOTICE}" in summary
    assert "Verdict" not in summary and "Testing" not in summary and "explore_gap" not in summary
    assert summary.endswith(f"Survey, design sheets and the free launch kit: {BASE}/s/abc123def456\n{CREDIT}")
    assert CREDIT == "Data: Qloo taste data · OpenStreetMap (© OpenStreetMap contributors) · Valhalla routing."
    assert progress[0] == "Found Williamsburg, Brooklyn, Kings County, New York, United States (40.7145, -73.9580)"
    assert f"Survey started: {BASE}/s/abc123def456" in progress
    assert "Tracing a 10-minute walk over the street network" in progress


def test_open_intent_reports_the_verdict_and_the_chain_line():
    events = survey_events("82e186998efa", label="Site at 40.7736, -73.9566", intent="open", business="Starbucks",
                           travel="distance", km=25.0, area="25 km drive", verdict=VERDICT)
    api = FakeApi({"/api/run": lambda request: stream(sse(events))})

    summary = asyncio.run(api.walkin().survey(lat=40.7736, lon=-73.9566, travel="distance", km=25.0, business=" Starbucks "))

    (run,) = api.requests  # coordinates need no address search
    assert dict(run.url.params) == {
        "lat": "40.773600", "lon": "-73.956600", "label": "Site at 40.7736, -73.9566", "travel": "distance", "km": "25.0",
        "ages": "all", "intent": "open", "business": "Starbucks",
    }
    lines = summary.splitlines()
    assert lines[1:4] == ["- Area: 25 km drive (1.56 km², traced over the street network)", "- Age focus: everyone",
                          "- Testing: Starbucks"]
    assert f"**Verdict:** {VERDICT['headline']}" in lines
    assert f"**Chain:** {VERDICT['chain']['line']}" in lines
    assert lines.index(f"**Verdict:** {VERDICT['headline']}") < lines.index("**Top gaps** (5 of 6 categories ranked, most missing first)")


def test_a_verdict_without_a_chain_has_no_chain_line():
    verdict = {**VERDICT, "chain": None, "headline": "Bakery is one of the strongest gaps here: #1 of 9 categories measured."}
    events = survey_events(intent="open", business="a bakery", verdict=verdict)
    api = FakeApi({"/api/run": lambda request: stream(sse(events))})
    summary = asyncio.run(api.walkin().survey(lat=40.7, lon=-73.9, business="a bakery"))
    assert "**Verdict:** Bakery is one of the strongest gaps here: #1 of 9 categories measured." in summary
    assert "**Chain:**" not in summary


def test_an_error_event_ends_the_survey_with_its_message():
    run, *_ = survey_events()
    message = "Qloo is not answering right now. Try again in a few minutes."
    events = [run, ("error", {"message": message}), ("done", {"run_id": "abc123def456", "seconds": 3.0})]
    api = FakeApi({"/api/run": lambda request: stream(sse(events))})
    summary = asyncio.run(api.walkin().survey(lat=40.7, lon=-73.9))
    assert f"**The survey stopped:** {message}" in summary
    assert "Top gaps" not in summary and "Concepts" not in summary
    assert f"{BASE}/s/abc123def456" in summary


def test_too_many_surveys_is_a_plain_sentence():
    api = FakeApi({"/api/run": lambda request: httpx.Response(
        429, json={"detail": "Too many runs from this address. Try again in an hour."})})
    message = fail(call=api.walkin().survey(lat=40.7, lon=-73.9))
    assert message == TOO_MANY_SURVEYS == "Walk-in allows a few surveys per hour from one address; try again later."


@pytest.mark.parametrize("detail", [
    "Walk time must be 5 to 60 minutes", "A road distance must be 1 to 100 km", "Say which business you want to open",
])
def test_a_bad_request_passes_on_the_servers_message(detail):
    api = FakeApi({"/api/run": lambda request: httpx.Response(400, json={"detail": detail})})
    assert fail(call=api.walkin().survey(lat=40.7, lon=-73.9, minutes=90)) == detail


def test_other_failures_are_plain_sentences():
    invalid = FakeApi({"/api/run": lambda request: httpx.Response(422, json={"detail": [
        {"type": "less_than_equal", "loc": ["query", "lat"], "msg": "Input should be less than or equal to 90"}]})})
    assert fail(call=invalid.walkin().survey(lat=95, lon=0)) == (
        "Walk-in could not read the request: lat: Input should be less than or equal to 90.")

    nowhere = FakeApi({"/api/geocode": lambda request: httpx.Response(200, json=[])})
    assert fail(call=nowhere.walkin().survey(place="Nowhere at all")) == (
        "Walk-in's address search found nothing for \"Nowhere at all\". Try a fuller address, or give lat and lon.")

    no_search = FakeApi({"/api/geocode": lambda request: httpx.Response(502, json={"detail": "Address search is unavailable right now."})})
    assert fail(call=no_search.walkin().survey(place="Williamsburg, Brooklyn")) == (
        "Address search is unavailable right now. Give the site's lat and lon instead.")
    assert [request.url.path for request in no_search.requests] == ["/api/geocode"]  # no survey started

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    down = Walkin(BASE, transport=httpx.MockTransport(refuse))
    assert fail(call=down.survey(lat=40.7, lon=-73.9)) == (
        f"Could not reach Walk-in at {BASE} (connection refused). Check the connection, or WALKIN_URL.")

    page = FakeApi({"/api/run": lambda request: httpx.Response(200, html="<!doctype html><title>Walk-in</title>")})
    assert "did not send a survey stream" in fail(call=page.walkin().survey(lat=40.7, lon=-73.9))

    unused = FakeApi({})
    assert "Say where the storefront is" in fail(call=unused.walkin().survey(lat=40.7))
    assert "3 to 160 characters" in fail(call=unused.walkin().survey(place="NY"))
    assert unused.requests == []  # told before asking Walk-in anything


def test_waits_while_the_free_server_wakes_up():
    answers = iter([
        httpx.Response(503, json={"detail": "The survey engine is waking up.", "waking": True}, headers={"retry-after": "3"}),
        httpx.Response(503, html="<html>Render is starting your service</html>"),  # the host's own page
    ])
    events = survey_events()

    def run(request: httpx.Request) -> httpx.Response:
        answer = next(answers, None)
        return stream(sse(events)) if answer is None else answer

    api = FakeApi({"/api/run": run})
    naps: list[float] = []

    async def nap(seconds: float) -> None:
        naps.append(seconds)

    progress: list[str | None] = []

    async def notify(message: str | None = None) -> None:
        progress.append(message)

    summary = asyncio.run(api.walkin(sleep=nap).survey(lat=40.7, lon=-73.9, progress=notify))
    assert naps == [3.0, 3.0] and len(api.requests) == 3
    assert progress[:2] == ["Walk-in's free server is waking up; that takes about a minute."] * 2
    assert "1. **Bakery**: Clear gap" in summary


def test_a_survey_still_running_when_the_wait_ends_comes_back_with_its_link():
    first = sse(survey_events()[:7]).encode()  # up to the gaps

    async def slow():
        yield first
        await asyncio.sleep(30)
        yield b""

    api = FakeApi({"/api/run": lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=slow())})
    summary = asyncio.run(api.walkin(survey_wait=0.2).survey(lat=40.7, lon=-73.9))
    assert "1. **Bakery**: Clear gap" in summary and "**Concepts**" not in summary
    assert ("**Not finished:** this is what the survey had found when this tool stopped waiting after 0.2 seconds. It may "
            "still be running at Walk-in: call get_survey(\"abc123def456\") in a minute for the rest, or open the link below.") in summary
    assert f"{BASE}/s/abc123def456" in summary


def test_settings_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("WALKIN_URL", raising=False)
    monkeypatch.delenv("WALKIN_WAIT_SECONDS", raising=False)
    assert (Walkin().base, Walkin().survey_wait) == ("https://walkin-app.pages.dev", 240.0)
    monkeypatch.setenv("WALKIN_URL", " http://127.0.0.1:8772/ ")
    monkeypatch.setenv("WALKIN_WAIT_SECONDS", "50")
    assert (Walkin().base, Walkin().survey_wait) == ("http://127.0.0.1:8772", 50.0)
    monkeypatch.setenv("WALKIN_WAIT_SECONDS", "2")
    assert Walkin().survey_wait == 10.0
    monkeypatch.setenv("WALKIN_WAIT_SECONDS", "soon")
    assert Walkin().survey_wait == 240.0


# ---------- list_examples ----------

EXAMPLES = [
    {"run_id": "b21ec69b0e92", "url": "/s/b21ec69b0e92", "label": "Zamalek, Cairo", "intent": "explore", "business": None,
     "area": "10 km drive", "ages": None, "llm": True, "headline": "Smash & Shroom", "verdict": None,
     "concepts": ["Smash & Shroom", "Aura Brew & Press", "Willow Table"], "gaps": 8,
     "top_gaps": ["Personal care", "Hamburger restaurant", "Coffee shop"],
     "kit": {"token": "kit7", "index": 0, "name": "Smash & Shroom", "url": "/k/kit7", "report_url": "/k/kit7/dossier"}},
    {"run_id": "82e186998efa", "url": "/s/82e186998efa", "label": "Upper East Side, Manhattan", "intent": "open",
     "business": "Starbucks", "area": "10-minute walk", "ages": "25–34", "llm": True, "headline": "Eastside Reserve Roasters",
     "verdict": VERDICT["headline"], "concepts": ["Eastside Reserve Roasters", "Madison & Dusk"], "gaps": 8,
     "top_gaps": ["New American", "Lounge", "Brunch"], "kit": None},
]


def test_list_examples_gives_each_survey_with_its_kit_and_report_links():
    api = FakeApi({"/api/examples": lambda request: httpx.Response(200, json=EXAMPLES)})
    summary = asyncio.run(api.walkin().examples())
    assert [request.url.path for request in api.requests] == ["/api/examples"]
    assert summary.splitlines() == [
        "## Walk-in examples: 2 finished surveys anyone can open (opening them costs nothing)",
        "1. **Zamalek, Cairo** · 10 km drive · run id b21ec69b0e92",
        "   - 8 categories ranked; most missing: Personal care, Hamburger restaurant, Coffee shop",
        "   - Concepts: Smash & Shroom, Aura Brew & Press, Willow Table",
        f"   - Survey: {BASE}/s/b21ec69b0e92",
        f"   - Launch kit (Smash & Shroom): {BASE}/k/kit7 · Report: {BASE}/k/kit7/dossier",
        "2. **Upper East Side, Manhattan** · 10-minute walk · for 25–34 · run id 82e186998efa",
        f"   - Testing Starbucks: {VERDICT['headline']}",
        "   - 8 categories ranked; most missing: New American, Lounge, Brunch",
        "   - Concepts: Eastside Reserve Roasters, Madison & Dusk",
        f"   - Survey: {BASE}/s/82e186998efa",
        "",
        "get_survey reads any of them in full: its top gaps with their evidence, and its concepts.",
        CREDIT,
    ]


def test_no_examples_says_so():
    api = FakeApi({"/api/examples": lambda request: httpx.Response(200, json=[])})
    assert asyncio.run(api.walkin().examples()) == "Walk-in lists no finished example surveys right now."


# ---------- get_survey ----------

def record_of(events: list[tuple[str, dict]], status: str = "complete", run_id: str = "82e186998efa") -> dict:
    return {"id": run_id, "status": status, "created_at": "2026-10-20T11:30:00Z",
            "events": [[name, data, round(index * 1.5, 1)] for index, (name, data) in enumerate(events)]}


def test_get_survey_reads_a_saved_survey_like_a_live_one():
    events = survey_events("82e186998efa", intent="open", business="Starbucks", verdict=VERDICT)
    api = FakeApi({
        "/api/runs/82e186998efa": lambda request: httpx.Response(200, json=record_of(events)),
        "/api/run": lambda request: stream(sse(events)),
    })
    walkin = api.walkin()
    saved = asyncio.run(walkin.record("82e186998efa"))
    assert saved == asyncio.run(walkin.survey(lat=40.7145, lon=-73.958, business="Starbucks"))
    assert f"**Chain:** {VERDICT['chain']['line']}" in saved
    assert saved.endswith(f"{BASE}/s/82e186998efa\n{CREDIT}")
    assert asyncio.run(walkin.record("https://walkin-app.pages.dev/s/82e186998efa?from=share")) == saved


def test_get_survey_says_whether_it_is_still_running_or_failed():
    running = survey_events()[:7]
    api = FakeApi({
        "/api/runs/abc123def456": lambda request: httpx.Response(200, json=record_of(running, "running", "abc123def456")),
        "/api/runs/f00": lambda request: httpx.Response(200, json=record_of(survey_events("f00")[:4], "failed", "f00")),
        "/api/runs/gone": lambda request: httpx.Response(404, json={"detail": "Survey not found."}),
    })
    walkin = api.walkin()
    summary = asyncio.run(walkin.record("abc123def456"))
    assert "1. **Bakery**: Clear gap" in summary
    assert "**Still running:** this is what it has found so far; ask again in a minute." in summary
    assert "**The survey did not finish:** Walk-in saved it as failed." in asyncio.run(walkin.record("f00"))
    assert fail(call=walkin.record("gone")) == "Survey not found."
    assert "A survey id is" in fail(call=walkin.record("../api/health"))
    assert [request.url.path for request in api.requests] == ["/api/runs/abc123def456", "/api/runs/f00", "/api/runs/gone"]


def test_the_summary_reports_only_what_the_events_say():
    assert summarize([], BASE) == f"## Walk-in survey: a storefront\n{CREDIT}"
    saved_before_labels = [
        ("run", {"run_id": "old1", "site": {"label": "Fort Greene", "minutes": 15}, "llm": False}),
        ("gaps", {"rows": [{"genre": "Bakery", "evidence": ["Demand is stronger here."]}]}),
        ("concepts", {"concepts": [], "mode": "none", "note": "Not enough Qloo data around this site."}),
    ]
    assert summarize(saved_before_labels, BASE).splitlines() == [
        "## Walk-in survey: Fort Greene",
        "- Area: 15-minute walk",
        "- Age focus: everyone",
        "",
        "**Top gaps** (1 of 1 categories ranked, most missing first)",
        "1. **Bakery**",
        "   - Demand is stronger here.",
        "",
        "**Concepts:** none. Not enough Qloo data around this site.",
        "",
        f"Survey, design sheets and the free launch kit: {BASE}/s/old1",
        CREDIT,
    ]


# ---------- Over the MCP protocol ----------

def test_the_tools_over_the_mcp_protocol(monkeypatch):
    events = survey_events("82e186998efa", intent="open", business="Starbucks", verdict=VERDICT)
    surveys = [stream(sse(events))]

    def run(request: httpx.Request) -> httpx.Response:  # one survey, then the rate limit
        return surveys.pop() if surveys else httpx.Response(429, json={"detail": "Too many runs from this address."})

    api = FakeApi({
        "/api/geocode": lambda request: httpx.Response(200, json=[{"label": "Zamalek, Cairo, Egypt", "lat": 30.06, "lon": 31.22}]),
        "/api/run": run,
        "/api/examples": lambda request: httpx.Response(200, json=EXAMPLES),
        "/api/runs/b21ec69b0e92": lambda request: httpx.Response(200, json=record_of(survey_events("b21ec69b0e92"), run_id="b21ec69b0e92")),
    })
    monkeypatch.setattr(walkin_mcp, "connect", api.walkin)
    progress: list[tuple[float, str | None]] = []

    async def on_progress(value: float, total: float | None, message: str | None) -> None:
        progress.append((value, message))

    async def session():
        async with create_connected_server_and_client_session(walkin_mcp.mcp) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            survey = await client.call_tool(
                "survey_storefront", {"lat": 40.7736, "lon": -73.9566, "business": "Starbucks"}, progress_callback=on_progress,
            )
            examples = await client.call_tool("list_examples", {})
            saved = await client.call_tool("get_survey", {"run_id": "b21ec69b0e92"})
            limited = await client.call_tool("survey_storefront", {"place": "Zamalek, Cairo"})
            return tools, survey, examples, saved, limited

    tools, survey, examples, saved, limited = asyncio.run(session())

    assert set(tools) == {"survey_storefront", "list_examples", "get_survey"}
    schema = tools["survey_storefront"].inputSchema
    assert set(schema["properties"]) == {"place", "lat", "lon", "travel", "minutes", "km", "ages", "business"}
    assert schema["properties"]["travel"]["enum"] == ["walk", "drive", "distance"]
    assert schema["properties"]["ages"]["enum"] == ["all", "under_25", "25_34", "35_54", "55_plus"]
    assert tools["get_survey"].inputSchema["required"] == ["run_id"]
    assert tools["list_examples"].annotations.readOnlyHint and not tools["survey_storefront"].annotations.readOnlyHint

    assert not survey.isError and f"**Verdict:** {VERDICT['headline']}" in survey.content[0].text
    assert not examples.isError and "Launch kit (Smash & Shroom)" in examples.content[0].text
    assert not saved.isError and saved.content[0].text.startswith("## Walk-in survey: Williamsburg, Brooklyn")
    assert limited.isError and TOO_MANY_SURVEYS in limited.content[0].text

    values = [value for value, _ in progress]
    keep_alives = len(events) // 2  # sse() sends one after every second event
    assert values == list(range(1, len(events) + keep_alives + 1))  # one per event and keep-alive, rising
    assert progress[:3] == [
        (1, f"Survey started: {BASE}/s/82e186998efa"),
        (2, "Tracing a 10-minute walk over the street network"),
        (3, "Tracing a 10-minute walk over the street network"),  # a keep-alive repeats the step under way
    ]
    assert all(message for _, message in progress)
