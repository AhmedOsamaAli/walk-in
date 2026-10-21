"""HTTP layer: composes the services, streams survey runs over server-sent events and serves the web app."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine, schemas, scoring
from .answers import AnswerCache
from .catchment import ALLOWED_MINUTES, CatchmentService
from .config import ROOT, settings
from .geocode import Geocoder
from .images import Images, explain_failure
from .llm import LLM
from .providers import build_images, build_llm
from .qloo import QlooClient, QlooError
from .ratelimit import DailyBudget, RateLimiter, client_ip
from .survey import concepts, pipeline
from .survey import design as designs
from .survey.models import RunStore, Site

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
# FastAPI's interactive API docs load Swagger UI and ReDoc from jsDelivr, with one inline bootstrap script.
DOCS_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: https:",
    "connect-src 'self'",
    "worker-src blob:",
    "frame-ancestors 'none'",
])


@dataclass
class Services:
    """Everything the endpoints talk to; swapped for fakes in tests."""

    qloo: QlooClient
    walker: CatchmentService
    llm: LLM
    images: Images
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


@router.get("/health", response_model=schemas.Health)
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


@router.get("/presets", response_model=list[schemas.Preset])
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
    size_m2: float | None = Query(None, ge=10, le=2000, description="Floor area of the unit in square meters"),
    kitchen: Literal["full", "light", "none"] | None = Query(None, description="The kitchen the unit has"),
    outdoor: bool | None = Query(None, description="Whether the unit has outdoor space"),
    intent: Literal["explore", "open", "improve"] = Query("explore", description="What the owner wants"),
    business: str = Query("", max_length=80, description="The business to open (intent=open)"),
    place_id: str = Query("", max_length=64, pattern=r"^[A-Za-z0-9-]*$", description="The owner's place (intent=improve)"),
) -> StreamingResponse:
    if focus not in FOCUS_OPTIONS:
        raise HTTPException(400, "Unknown focus")
    if minutes not in ALLOWED_MINUTES:
        raise HTTPException(400, "Walk time must be 5, 10 or 15 minutes")
    if intent == "open" and not business.strip():
        raise HTTPException(400, "Say which business you want to open")
    if intent == "improve" and not place_id:
        raise HTTPException(400, "Pick your place first")
    if not request.app.state.run_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many runs from this address. Try again in an hour.")

    services: Services = request.app.state.services
    runs: RunStore = request.app.state.runs
    site = Site(
        lat=lat, lon=lon, label=label.strip() or "Selected site", focus=focus, notes=notes.strip(), minutes=minutes,
        size_m2=size_m2, kitchen=kitchen, outdoor=outdoor, intent=intent, business=business.strip(), place_id=place_id,
    )
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        await queue.put((event, data))

    async def produce() -> None:
        tasks = [pipeline.analyze_site(services.qloo, services.walker, services.llm, runs, site, emit, services.answers)]
        if services.llm.enabled:
            async def baseline() -> None:
                try:
                    await emit("baseline", {"concepts": await concepts.baseline_concepts(services.llm, site, services.answers)})
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
                except TimeoutError:
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


@router.post("/design", response_model=schemas.DesignSheet)
async def design(request: Request, body: DesignRequest) -> dict:
    run_state = request.app.state.runs.get(body.run_id)
    if not run_state or not (0 <= body.index < len(run_state.concepts)):
        raise HTTPException(404, "Run or concept not found. Run the site again.")
    if body.index in run_state.designs:
        return run_state.designs[body.index]
    if not request.app.state.design_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many design requests. Try again later.")
    services: Services = request.app.state.services
    result = await designs.design_concept(
        services.llm, services.images, run_state, body.index, services.qloo, services.answers,
    )
    run_state.designs[body.index] = result
    return result


@router.post("/render", response_model=schemas.Render, response_model_exclude_unset=True)
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
        saved = designs.saved_render(services.images, shot, services.answers)
        if saved:
            return {"image": saved[0], "model": saved[1]}
        # Resuming a render that is still queued is not a new render, so it does not count against the limits.
        if key not in run_state.queued:
            if not request.app.state.render_limiter.allow(client_ip(request)):
                raise HTTPException(429, "Too many renders from this address. Try again later.")
            if not request.app.state.render_budget.allow():
                raise HTTPException(429, "Today's render budget is used up. Try again tomorrow.")
        task = asyncio.ensure_future(designs.render(services.images, shot, services.answers))
        run_state.renders[key] = task
    try:
        image, model = await asyncio.shield(task)
    except Exception as exc:
        if run_state.renders.get(key) is task:
            run_state.renders.pop(key)  # a failed render can be retried
            if isinstance(exc, TimeoutError):
                run_state.queued.add(key)
            else:
                run_state.queued.discard(key)
        if isinstance(exc, TimeoutError):
            # Still queued on free volunteer GPUs: not an error; the client asks again and resumes the job.
            return JSONResponse({"image": None, "model": None, "queued": True, "detail": explain_failure(exc)}, 202)
        log.warning("Render failed", exc_info=True)
        raise HTTPException(502, explain_failure(exc)) from exc
    run_state.queued.discard(key)
    return {"image": image, "model": model}


@router.get("/catchment", response_model=schemas.Catchment)
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


@router.get("/heatmap", response_model=schemas.Heatmap)
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


@router.get("/places", response_model=list[schemas.PlaceHit])
async def places(
    request: Request,
    q: str = Query(..., min_length=2, max_length=80),
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
) -> list[dict]:
    """The owner's place: Qloo places matching a name within about 3 km, nearest first."""
    if not request.app.state.map_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many searches. Try again later.")
    try:
        found = await engine.search_places(request.app.state.services.qloo, q, lat, lon)
    except QlooError as exc:
        raise HTTPException(502, str(exc)) from exc
    cards, seen = [], set()
    for entity in found:
        card = scoring.place_card(entity, (lat, lon))
        key = (card["name"], card["address"])
        if card["lat"] is None or key in seen:
            continue
        seen.add(key)
        cards.append({k: card[k] for k in ("id", "name", "address", "genres", "rating", "lat", "lon", "distance_m")})
    return sorted(cards, key=lambda c: c["distance_m"])


@router.get("/geocode", response_model=list[schemas.GeocodeHit])
async def geocode(request: Request, q: str = Query(..., min_length=3, max_length=160)) -> list[dict]:
    try:
        return await request.app.state.services.geocoder.search(q)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Address search is unavailable right now.") from exc


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers must revalidate, so a redeploy is picked up immediately.

    Vite's hashed bundles under assets/ never change, so those are cached for a year.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        immutable = path.startswith("assets/") and response.status_code == 200
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return response


def web_root() -> Path:
    """The React build (npm run build in frontend/) when it exists, otherwise the original static page."""
    built = ROOT / "frontend" / "dist"
    return built if (built / "index.html").exists() else ROOT / "web"


def create_app(services_factory: Callable[[], Services] = default_services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = services_factory()
        app.state.services = services
        app.state.runs = RunStore()
        app.state.run_limiter = RateLimiter(RUNS_PER_HOUR, 3600)
        app.state.design_limiter = RateLimiter(DESIGNS_PER_HOUR, 3600)
        app.state.render_limiter = RateLimiter(RENDERS_PER_HOUR, 3600)
        app.state.render_budget = DailyBudget(settings.image_daily_limit)
        app.state.map_limiter = RateLimiter(MAP_REQUESTS_PER_HOUR, 3600)
        try:
            yield
        finally:
            await services.aclose()

    app = FastAPI(
        title="Blank Space",
        version="1.0.0",
        description=(
            "Reads Qloo taste data for a real walking catchment, ranks what the block is missing and designs the "
            "business. GET /api/run streams a survey as server-sent events; the other endpoints are JSON."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        docs = request.url.path in ("/docs", "/redoc")
        response.headers.setdefault("Content-Security-Policy", DOCS_POLICY if docs else CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    app.include_router(router)
    app.mount("/", RevalidatingStaticFiles(directory=web_root(), html=True), name="web")
    return app


app = create_app()
