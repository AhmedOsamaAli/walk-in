"""A survey run: the walk, the block, demand, taste and gaps from Qloo, the gaps cross-checked with the places
OpenStreetMap shows inside the walk, then what the owner asked for, streamed as events.

Intents: "explore" designs the three strongest concepts; "open" first judges the business the owner wants to open and
designs it first; "improve" compares the owner's existing place with the places people here love in its category.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from .. import engine, osm, scoring
from ..answers import AnswerCache
from ..catchment import Catchment, CatchmentService, simplified
from ..demographics import ages_label
from ..llm import LLM
from ..qloo import QlooClient, QlooError, track_reads
from . import constraints, intents
from .concepts import caution, concepts_from_agent, rule_concepts
from .evidence import annotate, people_here, public_gap
from .models import Emit, RunState, RunStore, Site

log = logging.getLogger("walkin")

OSM_FAILED = "OpenStreetMap did not answer in time, so the gaps rest on Qloo's places alone and say they were not cross-checked."
# OpenStreetMap's free servers answer a walk's places in seconds; a big drive holds tens of thousands and times out.
OSM_MAX_KM2 = 30
OSM_TOO_BIG = ("This area is larger than {limit} km², too large for OpenStreetMap's free servers, so the gaps rest on "
               "Qloo's places alone and say they were not cross-checked.")
OSM_TOO_BIG_NOTE = "Not cross-checked: OpenStreetMap is read for areas up to {limit} km², and this one is larger."


def read_notes(site: Site) -> constraints.Constraints:
    """The owner's notes as rules; unit details written in the notes ('60 m², no kitchen') fill what the form left out."""
    rules = constraints.parse(site.notes)
    if site.size_m2 is None and rules.size_m2:
        site.size_m2 = rules.size_m2
    if site.kitchen is None and rules.kitchen:
        site.kitchen = rules.kitchen
    if site.outdoor is None and rules.outdoor is not None:
        site.outdoor = rules.outdoor
    return rules


async def analyze_site(
    q: QlooClient, walker: CatchmentService, llm: LLM, store: RunStore, site: Site, emit: Emit,
    answers: AnswerCache | None = None, run_id: str | None = None, osm_client: osm.OsmClient | None = None,
) -> RunState:
    run = RunState(id=run_id or uuid.uuid4().hex[:12], site=site, constraints=read_notes(site))
    started, calls_before, hits_before = time.time(), q.calls, q.cache_hits
    reads = track_reads()
    osm.track(None)
    checking: asyncio.Future | None = None
    await emit("run", {
        "run_id": run.id, "site": site.__dict__, "llm": llm.enabled, "understood": run.constraints.understood,
        "area_label": site.area, "ages_label": ages_label(site.ages),
    })

    async def step(name: str, label: str, coro):
        await emit("status", {"step": name, "state": "running", "label": label})
        result = await coro
        await emit("status", {"step": name, "state": "done", "label": label})
        return result

    who = people_here(site.ages)
    try:
        if site.intent == "improve":
            run.place = await step("place", "Finding your place on Qloo", engine.place_by_id(q, site.place_id))
            location = scoring.place_location(run.place) if run.place else None
            if not location:
                await emit("error", {"message": "That place is not on Qloo, so it cannot be compared. Try another search."})
                return run
            site.lat, site.lon = location
            site.label = run.place.get("name") or site.label
            await emit("place", {"place": scoring.place_card(run.place, location), "site": site.__dict__})

        catchment = await step(
            "walk", f"Tracing a {site.area} over the street network", walker.area(site.lat, site.lon, site.reach)
        )
        # Every Qloo request below sends the outline; a drive's is simplified once, off the event loop.
        catchment = await simplified(catchment)
        run.catchment = catchment
        await emit("catchment", catchment.public())
        # OpenStreetMap is asked alongside Qloo; the gaps wait for it only once Qloo's evidence is in.
        check = osm.track(osm.CrossCheck(None, catchment))
        if osm_client is not None:
            checking = asyncio.ensure_future(cross_check(osm_client, catchment, check, emit))
        (block, closed), (genres, cues), taste = await asyncio.gather(
            step("block", f"Reading every place inside the {site.area}", engine.scan_walk(q, catchment)),
            step("demand", f"Ranking what {who} engage with against same-size areas around",
                 engine.demand_genres(q, catchment, site.ages)),
            step("taste", "Finding the brands, artists, films, shows and podcasts this area over-indexes on",
                 engine.local_taste(q, site.lat, site.lon, site.ages, engine.taste_m(catchment))),
        )
        check.learn(block + closed)
        run.block, run.genres, run.cues, run.taste = block, genres, cues, taste
        run.summary = scoring.summarize_block(block)
        await emit("block", {
            "summary": run.summary,
            "places": [scoring.place_card(p, (site.lat, site.lon)) for p in block],
        })
        await emit("demand", {"genres": genres[:12], "cues": cues})
        await emit("taste", taste)

        gaps = await step(
            "gaps", "Comparing supply with the surroundings and finding places people here love more than the rest of the city",
            engine.gap_table(q, catchment, genres, site.focus, checking if checking is not None else check, site.ages),
        )
        run.gaps = [annotate(run, row) for row in gaps]
        await emit("gaps", {"rows": [public_gap(g) for g in run.gaps]})

        if site.intent == "improve":
            run.improve = await step("improve", "Comparing your place with the ones people here love", intents.improve(q, run))
            await emit("improve", run.improve or {"note": "Qloo has no category for this place, so there is nothing to compare."})
            return run
        if site.intent == "open" and site.business.strip():
            run.verdict = await step("verdict", f"Judging {site.business.strip()[:40]} for this site", intents.verdict(q, run))
            await emit("verdict", run.verdict)
        await design_concepts(q, llm, run, emit, answers)
    except QlooError as exc:
        await emit("error", {"message": str(exc)})
    finally:
        if checking is not None and not checking.done():
            checking.cancel()  # the survey stopped before its gaps needed OpenStreetMap
        store.add(run)
        calls, hits = q.calls - calls_before, q.cache_hits - hits_before
        await emit("done", {
            "run_id": run.id,
            "seconds": round(time.time() - started, 1),
            "qloo_calls": calls,
            "cache_hits": hits,
            # Every Qloo answer the survey read, and when the oldest came from Qloo (clients that don't count reads
            # fall back to the counters above).
            "qloo_queries": reads.queries or calls + hits,
            "data_as_of": datetime.fromtimestamp(reads.oldest, UTC).isoformat() if reads.oldest else None,
        })
    return run


async def cross_check(client: osm.OsmClient, catchment: Catchment, check: osm.CrossCheck, emit: Emit) -> osm.CrossCheck:
    """Fills the survey's cross-check with the places OpenStreetMap shows inside the walk, as a step of its own; when no
    instance answers in time, the step fails, the log says why and the survey goes on. An area too large for the free
    servers is not asked at all, and the survey says so."""
    if catchment.area_m2 > OSM_MAX_KM2 * 1e6:
        check.scan = osm.Scan(checked=False, note=OSM_TOO_BIG_NOTE.format(limit=OSM_MAX_KM2), reason="too_big")
        await emit("notice", {"message": OSM_TOO_BIG.format(limit=OSM_MAX_KM2)})
        return check
    await emit("status", {"step": "osm", "state": "running", "label": osm.LABEL})
    check.scan = await client.scan(catchment)
    await emit("status", {"step": "osm", "state": "done" if check.checked else "failed", "label": osm.LABEL})
    if not check.checked:
        await emit("notice", {"message": OSM_FAILED})
    return check


async def design_concepts(q: QlooClient, llm: LLM, run: RunState, emit: Emit, answers: AnswerCache | None) -> None:
    if not run.gaps:
        note = (
            "Not enough Qloo data around this site." if run.site.focus == "any" else
            f"None of the place types Qloo ranks for people here is {scoring.FOCUS_NAMES[run.site.focus]}, so Qloo points "
            "to no gap of that kind. Try any business."
        )
        await emit("concepts", {"concepts": [], "mode": "none", "note": note})
        return
    await emit("status", {"step": "concepts", "state": "running", "label": "Designing concepts from the gaps"})
    concepts, mode, about = [], "rules", {}
    if llm.enabled:
        concepts, about = await concepts_from_agent(llm, q, run, emit, answers)
        mode = "agent" if concepts else "rules"
    if not concepts:
        # The rules read every favorite's reviews: seconds of work for a big drive, done where the server keeps answering.
        concepts, mode, about = await asyncio.to_thread(rule_concepts, run), "rules", {}
    if not concepts:
        reason = "your notes rule out" if any(row.get("ruled_out") for row in run.gaps) else "this unit cannot host"
        mode, about = "none", {"note": f"Every category the block is missing is one {reason}."}
    warning = caution(run, concepts)
    if warning:
        about = {**about, "caution": warning}
    run.concepts = concepts
    await emit("status", {"step": "concepts", "state": "done", "label": "Designing concepts from the gaps"})
    await emit("concepts", {"concepts": concepts, "mode": mode, **about})
