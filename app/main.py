"""FastAPI server: streams agent runs over server-sent events and serves the web app."""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, engine
from .catchment import ALLOWED_MINUTES, CatchmentService
from .config import ROOT, settings
from .llm import LLM
from .providers import build_images, build_llm
from .qloo import QlooClient, QlooError

FOCUS_OPTIONS = {"any", "food_drink", "retail", "leisure"}
RUNS_PER_HOUR = 20
DESIGNS_PER_HOUR = 40
HEATMAPS_PER_HOUR = 200

PRESETS = [
    {"id": "ues", "label": "Upper East Side, Manhattan", "lat": 40.7736, "lon": -73.9566,
     "blurb": "Quiet residential blocks whose favorite spots are all downtown"},
    {"id": "williamsburg", "label": "Williamsburg, Brooklyn", "lat": 40.7145, "lon": -73.9580,
     "blurb": "Bars and brunch everywhere. What is still missing?"},
    {"id": "les", "label": "Lower East Side, Manhattan", "lat": 40.7183, "lon": -73.9884,
     "blurb": "Dense, young and nocturnal"},
    {"id": "east_austin", "label": "East Austin, Texas", "lat": 30.2622, "lon": -97.7247,
     "blurb": "A fast-changing neighborhood beyond New York"},
    {"id": "zamalek", "label": "Zamalek, Cairo", "lat": 30.0626, "lon": 31.2197,
     "blurb": "Works beyond the US: Cairo's island district"},
]


class DesignRequest(BaseModel):
    run_id: str
    index: int


class RateLimiter:
    def __init__(self, limit: int, window_s: int) -> None:
        self.limit, self.window_s = limit, window_s
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class Geocoder:
    """OpenStreetMap Nominatim, throttled to its 1 request/second policy and cached in memory."""

    def __init__(self) -> None:
        self._cache: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._http = httpx.AsyncClient(
            base_url="https://nominatim.openstreetmap.org",
            headers={"User-Agent": "BlankSpace/0.1 (Qloo Agentic Hackathon demo)"},
            timeout=15,
        )

    async def search(self, query: str) -> list[dict]:
        key = query.strip().lower()
        if key in self._cache:
            return self._cache[key]
        async with self._lock:
            wait = 1.0 - (time.time() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            response = await self._http.get("/search", params={"q": query, "format": "jsonv2", "limit": 5})
            self._last = time.time()
        response.raise_for_status()
        results = [
            {"label": item.get("display_name"), "lat": float(item["lat"]), "lon": float(item["lon"])}
            for item in response.json()
        ]
        self._cache[key] = results
        return results

    async def aclose(self) -> None:
        await self._http.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.qloo = QlooClient(settings.qloo_api_key, settings.qloo_base_url, settings.cache_dir)
    app.state.llm = build_llm(settings)
    app.state.images = build_images(settings)
    app.state.runs = agent.RunStore()
    app.state.limiter = RateLimiter(RUNS_PER_HOUR, 3600)
    app.state.design_limiter = RateLimiter(DESIGNS_PER_HOUR, 3600)
    app.state.heatmap_limiter = RateLimiter(HEATMAPS_PER_HOUR, 3600)
    app.state.geocoder = Geocoder()
    app.state.walker = CatchmentService(settings.walk_cache_dir)
    yield
    await app.state.qloo.aclose()
    await app.state.geocoder.aclose()
    await app.state.walker.aclose()
    await app.state.images.aclose()


app = FastAPI(title="Blank Space", lifespan=lifespan)


def client_ip(request: Request) -> str:
    # The hosting proxy appends the address it saw, so the last entry cannot be forged by the client.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


@app.get("/api/health")
async def health(request: Request) -> dict:
    llm: LLM = request.app.state.llm
    return {"ok": True, "llm": llm.enabled, "model": llm.model if llm.enabled else None, "image": request.app.state.images.enabled}


@app.get("/api/presets")
async def presets() -> list[dict]:
    return PRESETS


@app.get("/api/run")
async def run(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    label: str = Query("Selected site", max_length=160),
    focus: str = Query("any"),
    notes: str = Query("", max_length=300),
    minutes: int = Query(10),
) -> StreamingResponse:
    if focus not in FOCUS_OPTIONS:
        raise HTTPException(400, "Unknown focus")
    if minutes not in ALLOWED_MINUTES:
        raise HTTPException(400, "Walk time must be 5, 10 or 15 minutes")
    if not request.app.state.limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many runs from this address. Try again in an hour.")

    site = agent.Site(
        lat=lat, lon=lon, label=label.strip() or "Selected site", focus=focus, notes=notes.strip(), minutes=minutes,
    )
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def produce() -> None:
        llm: LLM = request.app.state.llm
        state = request.app.state
        tasks = [agent.analyze_site(state.qloo, state.walker, llm, state.runs, site, emit)]
        if llm.enabled:
            async def baseline() -> None:
                try:
                    await emit("baseline", {"concepts": await agent.plain_llm_concepts(llm, site)})
                except Exception:
                    pass
            tasks.append(baseline())
        try:
            await asyncio.gather(*tasks)
        finally:
            await queue.put(None)

    async def stream():
        producer = asyncio.create_task(produce())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            if not producer.done():
                producer.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/design")
async def design(request: Request, body: DesignRequest) -> dict:
    state = request.app.state.runs.get(body.run_id)
    if not state or not (0 <= body.index < len(state.concepts)):
        raise HTTPException(404, "Run or concept not found. Run the site again.")
    if body.index in state.designs:
        return state.designs[body.index]
    if not request.app.state.design_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many design requests. Try again later.")
    result = await agent.design_concept(request.app.state.llm, request.app.state.images, state, body.index)
    state.designs[body.index] = result
    return result


@app.get("/api/catchment")
async def catchment(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    minutes: int = Query(10),
) -> dict:
    if minutes not in ALLOWED_MINUTES:
        raise HTTPException(400, "Walk time must be 5, 10 or 15 minutes")
    if not request.app.state.heatmap_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")
    walk = await request.app.state.walker.walk(lat, lon, minutes)
    return walk.public()


@app.get("/api/heatmap")
async def heatmap(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    tag: str = Query(..., min_length=10, max_length=120, pattern=r"^urn:tag:[a-z0-9_:]+$"),
) -> dict:
    if not request.app.state.heatmap_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")
    try:
        return {"cells": await engine.genre_heatmap(request.app.state.qloo, lat, lon, tag)}
    except QlooError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/geocode")
async def geocode(request: Request, q: str = Query(..., min_length=3, max_length=160)) -> list[dict]:
    try:
        return await request.app.state.geocoder.search(q)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Address search is unavailable right now.") from exc


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers must revalidate, so a redeploy is picked up immediately."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", RevalidatingStaticFiles(directory=ROOT / "web", html=True), name="web")
