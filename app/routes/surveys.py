"""Surveys: one runs and streams its events as server-sent events (GET /api/run), its record comes back after a
refresh or a restart (GET /api/runs/{id}) and each concept gets its design sheet (POST /api/design).

A survey outlives the request that started it: it runs to its end and is saved whether or not anyone still listens.
The database stays off its way: who ran it and its row are saved alongside the survey (Neon sleeps after five idle
minutes and its first query takes seconds), and its end once its start is. A finished survey's record is served from
memory (app.response_cache): it never changes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from .. import auth, cache_policy, jsonio, schemas
from ..catchment import make_reach
from ..config import settings
from ..db import SurveyStore
from ..db.surveys import survey_status
from ..ratelimit import client_ip
from ..response_cache import Page, page_response
from ..survey import concepts, pipeline, snapshot
from ..survey import design as designs
from ..survey.models import EventLog, RunState, RunStore, Site

if TYPE_CHECKING:
    from ..services import Services

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")

FOCUS_OPTIONS = {"any", "food_drink", "retail", "leisure"}
# What GET /api/run answers while surveys are paused (SURVEYS_PAUSED), once Qloo's hackathon key is switched off.
SURVEYS_PAUSED = "New surveys are paused; open one of the surveyed storefronts"


class DesignRequest(BaseModel):
    run_id: str
    index: int


class RunRecord(BaseModel):
    """A survey as it was streamed, so a page can be restored after a refresh or a restart."""

    id: str
    status: Literal["running", "complete", "failed"] = Field(
        description="'failed' when the survey stopped on an error (its error event says why) or a restart cut it off"
    )
    created_at: datetime
    events: list[list] = Field(description="Every event as streamed: [event, data, seconds since the survey started]")


@router.get("/run")
async def run(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    label: str = Query("Selected site", max_length=160),
    focus: str = Query("any"),
    notes: str = Query("", max_length=300),
    minutes: int = Query(10, description="Walk or drive time, 5 to 60 minutes"),
    travel: Literal["walk", "drive", "distance"] = Query("walk", description="How customers come: on foot, by car, or within a road distance"),
    km: float | None = Query(None, description="Road distance, 1 to 100 km (travel=distance)"),
    ages: Literal["all", "under_25", "25_34", "35_54", "55_plus"] = Query("all", description="Who the owner wants to serve"),
    size_m2: float | None = Query(None, ge=10, le=2000, description="Floor area of the unit in square meters"),
    kitchen: Literal["full", "light", "none"] | None = Query(None, description="The kitchen the unit has"),
    outdoor: bool | None = Query(None, description="Whether the unit has outdoor space"),
    intent: Literal["explore", "open", "improve"] = Query("explore", description="What the owner wants"),
    business: str = Query("", max_length=80, description="The business to open (intent=open)"),
    place_id: str = Query("", max_length=64, pattern=r"^[A-Za-z0-9-]*$", description="The owner's place (intent=improve)"),
) -> StreamingResponse:
    if settings.surveys_paused:
        raise HTTPException(503, SURVEYS_PAUSED)
    if focus not in FOCUS_OPTIONS:
        raise HTTPException(400, "Unknown focus")
    try:
        reach = make_reach(travel, minutes, km)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if intent == "open" and not business.strip():
        raise HTTPException(400, "Say which business you want to open")
    if intent == "improve" and not place_id:
        raise HTTPException(400, "Pick your place first")
    if not request.app.state.run_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many runs from this address. Try again in an hour.")

    services: Services = request.app.state.services
    runs: RunStore = request.app.state.runs
    surveys: SurveyStore = request.app.state.surveys
    session = request.cookies.get(auth.SESSION_COOKIE)
    device = auth.device_id(request)  # the survey is this browser's, and its user's once they sign in
    site = Site(
        lat=lat, lon=lon, label=label.strip() or "Selected site", focus=focus, notes=notes.strip(),
        minutes=reach.minutes, size_m2=size_m2, kitchen=kitchen, outdoor=outdoor, intent=intent,
        business=business.strip(), place_id=place_id, travel=reach.travel, km=reach.km, ages=ages,
    )
    asked = asdict(site)  # the site as the owner asked for it, before the survey fills in what the notes say
    survey = EventLog(uuid.uuid4().hex[:12])
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(event: str, data: dict) -> None:
        text = json.dumps(data, ensure_ascii=False)
        survey.record(event, jsonio.loads(text))  # a copy as sent, so later changes to the run cannot rewrite it
        await queue.put(f"event: {event}\ndata: {text}\n\n")

    async def record_start() -> dict | None:
        """Saves the survey's row as it starts, with who ran it when signed in; None once saved, else the start to
        write whole when the survey ends. Never raises: a database failure never stops a survey."""
        user_id = None
        try:
            user_id = await auth.session_user_id(request.app.state, session)
        except Exception:
            log.warning("Could not check the session; survey %s is saved signed out", survey.run_id, exc_info=True)
        start = {"request": asked, "created_at": survey.created_at, "user_id": user_id, "device_id": device}
        try:
            await surveys.start(survey.run_id, **start)
        except Exception:
            log.warning("Could not save survey %s as it started; saving it at its end", survey.run_id, exc_info=True)
            return start
        return None

    async def produce() -> None:
        """Runs the survey to its end and saves it, whether or not anyone is still listening. The database is kept off
        its way: who ran it and its row are saved alongside (Neon sleeps when idle and takes seconds to wake), and its
        end is saved once its start is."""
        starting = asyncio.ensure_future(record_start())
        tasks = [pipeline.analyze_site(
            services.qloo, services.walker, services.llm, runs, site, emit, services.answers, run_id=survey.run_id,
            osm_client=services.osm,
        )]
        # The no-data baseline answers "what should open here?", so it only stands next to concepts.
        if services.llm.enabled and site.intent != "improve":
            async def baseline() -> None:
                try:
                    await emit("baseline", {"concepts": await concepts.baseline_concepts(services.llm, site, services.answers)})
                except Exception:
                    log.warning("No-data baseline failed", exc_info=True)
            tasks.append(baseline())
        failed = True  # unless it runs to its end without an error
        ran: RunState | None = None  # the survey's state as the pipeline hands it back, whatever memory keeps meanwhile
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            ran = results[0] if isinstance(results[0], RunState) else None
            errors = [result for result in results if isinstance(result, BaseException)]
            for error in errors:
                log.error("Survey %s failed", survey.run_id, exc_info=error)
            failed = bool(errors) or any(event == "error" for event, *_ in survey.events)
        finally:
            survey.status = "failed" if failed else "complete"
            # The stream ends once the survey is saved, so a page reloaded at its end finds it finished.
            try:
                await save_survey(surveys, survey, ran or runs.get(survey.run_id), starting)
            finally:
                await queue.put(None)

    async def stream():
        # The survey starts once the response does, and is not tied to it: a client that refreshes or leaves does not
        # stop it.
        request.app.state.live.start(survey, produce())
        while True:
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=15)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": cache_policy.NO_STORE, "X-Accel-Buffering": "no"},
    )


async def save_survey(
    surveys: SurveyStore, survey: EventLog, run: RunState | None, starting: Awaitable[dict | None] | None = None,
) -> None:
    """Saves how a survey ended, once its start is saved (`starting`: None when it was, else the start to write whole);
    when its state cannot be stored, its events still are."""
    state = None
    try:
        state = snapshot.dump_run(run) if run else None
    except TypeError:
        log.warning("Survey %s is saved without its state", survey.run_id, exc_info=True)
    unsaved = await starting if starting is not None else None
    try:
        await surveys.finish(survey.run_id, survey.status, survey.events, state, headline(run), unsaved=unsaved)
    except Exception:
        log.warning("Could not save survey %s", survey.run_id, exc_info=True)


def headline(run: RunState | None) -> str | None:
    """What My places shows for a survey: its top concept's name, or its top gap."""
    if run is None:
        return None
    if run.concepts:
        name = run.concepts[0].get("name")
    elif run.gaps:
        name = run.gaps[0].get("genre")
    else:
        return None
    return name.strip() if isinstance(name, str) and name.strip() else None


@router.get("/runs/{run_id}", response_model=RunRecord)
async def run_record(request: Request, run_id: str) -> Response:
    """A survey's events as they were streamed: from memory while it runs, from the database afterwards (then from
    memory: a finished survey never changes)."""
    page = await run_page_for(request.app.state, run_id)
    if page is None:
        raise HTTPException(404, "Survey not found.")
    return page_response(page, cache_policy.for_run(run_id, page.status, settled=page.settled), request)


RECORD = TypeAdapter(RunRecord)


def record_body(record: dict) -> bytes:
    """A survey's record as JSON: the bytes FastAPI makes of it with RunRecord as the response model."""
    return RECORD.dump_json(RECORD.validate_python(record))


async def run_page_for(state, run_id: str) -> Page | None:
    """GET /api/runs/{id}'s page, or None for a survey that is neither running here nor saved."""
    live: EventLog | None = state.live.get(run_id)
    if live:  # running, or saving its end: not final, and kept by no one until it is saved
        record = {"id": run_id, "status": live.status, "created_at": live.created_at, "events": live.events}
        return Page(record_body(record), run_id, live.status, final=False, settled=False)

    async def read() -> Page | None:
        row = await state.surveys.get(run_id, with_state=False)  # the events are all the page needs
        if not row:
            return None
        status = survey_status(row["status"], row["created_at"], datetime.now(UTC))  # failed when a restart cut it off
        body = record_body({"id": row["id"], "status": status, "created_at": row["created_at"], "events": row["events"]})
        return Page(body, run_id, status, final=row["status"] in cache_policy.FINISHED)  # finished: it never changes

    return await state.responses.fetch(f"run:{run_id}", read)


@router.post("/design", response_model=schemas.DesignSheet)
async def design(request: Request, body: DesignRequest) -> dict:
    run_state = await request.app.state.runs.fetch(body.run_id)
    if not run_state or not (0 <= body.index < len(run_state.concepts)):
        raise HTTPException(404, "Run or concept not found. Run the site again.")
    if body.index in run_state.designs:
        return run_state.designs[body.index]
    if not request.app.state.design_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many design requests. Try again later.")
    services: Services = request.app.state.services
    result = await designs.design_concept(run_state, body.index, services.qloo)
    # When two requests design the same concept, the first sheet stays, in memory as in the database.
    result = run_state.designs.setdefault(body.index, result)
    try:
        await request.app.state.surveys.save_design(body.run_id, body.index, result)
    except Exception:
        log.warning("Could not save design sheet %d of survey %s", body.index, body.run_id, exc_info=True)
    return result
