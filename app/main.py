"""HTTP layer: composes the services, streams survey runs over server-sent events and serves the web app."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Callable, Literal

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, engine
from .answers import AnswerCache
from .catchment import ALLOWED_MINUTES, CatchmentService
from .config import ROOT, settings
from .geocode import Geocoder
from .images import ImageGen, explain_failure
from .llm import LLM
from .providers import build_images, build_llm
from .qloo import QlooClient, QlooError
from .ratelimit import DailyBudget, RateLimiter, client_ip

log = logging.getLogger("blankspace")

FOCUS_OPTIONS = {"any", "food_drink", "retail", "leisure"}
RUNS_PER_HOUR = 20
DESIGNS_PER_HOUR = 40
RENDERS_PER_HOUR = 24
MAP_REQUESTS_PER_HOUR = 200

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

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' https://unpkg.com",
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


@dataclass
class Services:
    """Everything the endpoints talk to; swapped for fakes in tests."""

    qloo: QlooClient
    walker: CatchmentService
    llm: LLM
    images: ImageGen
    geocoder: Geocoder
    answers: AnswerCache = field(default_factory=lambda: AnswerCache(None))

    async def aclose(self) -> None:
        for service in (self.qloo, self.walker, self.images, self.geocoder):
            await service.aclose()


def default_services() -> Services:
    return Services(
        qloo=QlooClient(settings.qloo_api_key, settings.qloo_base_url, settings.cache_dir),
        walker=CatchmentService(settings.walk_cache_dir),
        llm=build_llm(settings),
        images=build_images(settings),
        geocoder=Geocoder(),
        answers=AnswerCache(settings.agent_cache_dir, enabled=settings.agent_cache),
    )


class DesignRequest(BaseModel):
    run_id: str
    index: int


class RenderRequest(BaseModel):
    run_id: str
    index: int
    shot: Literal["interior", "exterior"]


router = APIRouter(prefix="/api")


@router.get("/health")
async def health(request: Request) -> dict:
    services: Services = request.app.state.services
    llm = services.llm
    return {
        "ok": True,
        "qloo": services.qloo.configured,
        "llm": llm.enabled,
        "model": llm.model if llm.enabled else None,
        "models": llm.models if llm.enabled else [],
        "resting": llm.resting() if llm.enabled else {},
        "image": services.images.enabled,
        "image_model": services.images.model,
    }


@router.get("/presets")
async def presets() -> list[dict]:
    return PRESETS


@router.get("/run")
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
    if not request.app.state.run_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many runs from this address. Try again in an hour.")

    services: Services = request.app.state.services
    runs: agent.RunStore = request.app.state.runs
    site = agent.Site(
        lat=lat, lon=lon, label=label.strip() or "Selected site", focus=focus, notes=notes.strip(), minutes=minutes,
    )
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def produce() -> None:
        tasks = [agent.analyze_site(services.qloo, services.walker, services.llm, runs, site, emit, services.answers)]
        if services.llm.enabled:
            async def baseline() -> None:
                try:
                    await emit("baseline", {"concepts": await agent.baseline_concepts(services.llm, site, services.answers)})
                except Exception:
                    log.warning("No-data baseline failed", exc_info=True)
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


@router.post("/design")
async def design(request: Request, body: DesignRequest) -> dict:
    run_state = request.app.state.runs.get(body.run_id)
    if not run_state or not (0 <= body.index < len(run_state.concepts)):
        raise HTTPException(404, "Run or concept not found. Run the site again.")
    if body.index in run_state.designs:
        return run_state.designs[body.index]
    if not request.app.state.design_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many design requests. Try again later.")
    services: Services = request.app.state.services
    result = await agent.design_concept(
        services.llm, services.images, run_state, body.index, services.qloo, services.answers,
    )
    run_state.designs[body.index] = result
    return result


@router.post("/render")
async def render(request: Request, body: RenderRequest) -> dict:
    """One AI render of a design sheet's shot, made once per run and cached across runs."""
    run_state = request.app.state.runs.get(body.run_id)
    design = run_state.designs.get(body.index) if run_state else None
    shot = next((s for s in (design or {}).get("shots", []) if s["kind"] == body.shot), None)
    if not shot:
        raise HTTPException(404, "Open the design sheet first.")
    services: Services = request.app.state.services
    if not services.images.enabled:
        return {"image": None, "model": None}
    key = (body.index, body.shot)
    task = run_state.renders.get(key)
    if task is None:
        saved = agent.saved_render(services.images, shot, services.answers)
        if saved:
            return {"image": saved, "model": services.images.model}
        if not request.app.state.render_limiter.allow(client_ip(request)):
            raise HTTPException(429, "Too many renders from this address. Try again later.")
        if not request.app.state.render_budget.allow():
            raise HTTPException(429, "Today's render budget is used up. Try again tomorrow.")
        task = asyncio.ensure_future(agent.render(services.images, shot, services.answers))
        run_state.renders[key] = task
    try:
        image = await asyncio.shield(task)
    except Exception as exc:
        if run_state.renders.get(key) is task:
            run_state.renders.pop(key)  # a failed render can be retried
        log.warning("Render failed", exc_info=True)
        raise HTTPException(502, explain_failure(exc)) from exc
    return {"image": image, "model": services.images.model}


@router.get("/catchment")
async def catchment(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    minutes: int = Query(10),
) -> dict:
    if minutes not in ALLOWED_MINUTES:
        raise HTTPException(400, "Walk time must be 5, 10 or 15 minutes")
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")
    walk = await request.app.state.services.walker.walk(lat, lon, minutes)
    return walk.public()


@router.get("/heatmap")
async def heatmap(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    tag: str = Query(..., min_length=10, max_length=120, pattern=r"^urn:tag:[a-z0-9_:]+$"),
) -> dict:
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many map requests. Try again later.")
    try:
        return {"cells": await engine.genre_heatmap(request.app.state.services.qloo, lat, lon, tag)}
    except QlooError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/geocode")
async def geocode(request: Request, q: str = Query(..., min_length=3, max_length=160)) -> list[dict]:
    try:
        return await request.app.state.services.geocoder.search(q)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Address search is unavailable right now.") from exc


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers must revalidate, so a redeploy is picked up immediately."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(services_factory: Callable[[], Services] = default_services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = services_factory()
        app.state.services = services
        app.state.runs = agent.RunStore()
        app.state.run_limiter = RateLimiter(RUNS_PER_HOUR, 3600)
        app.state.design_limiter = RateLimiter(DESIGNS_PER_HOUR, 3600)
        app.state.render_limiter = RateLimiter(RENDERS_PER_HOUR, 3600)
        app.state.render_budget = DailyBudget(settings.image_daily_limit)
        app.state.map_limiter = RateLimiter(MAP_REQUESTS_PER_HOUR, 3600)
        try:
            yield
        finally:
            await services.aclose()

    app = FastAPI(title="Blank Space", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    app.include_router(router)
    app.mount("/", RevalidatingStaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


app = create_app()
