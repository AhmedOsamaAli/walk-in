"""A survey run: the walk, the block, demand, taste and gaps from Qloo, then concepts, streamed as events."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from .. import engine, scoring
from ..answers import AnswerCache
from ..catchment import CatchmentService
from ..llm import LLM
from ..qloo import QlooClient, QlooError
from .concepts import concepts_from_agent, rule_concepts
from .evidence import public_gap, with_fit
from .models import Emit, RunState, RunStore, Site

log = logging.getLogger("blankspace")


async def analyze_site(
    q: QlooClient, walker: CatchmentService, llm: LLM, store: RunStore, site: Site, emit: Emit,
    answers: AnswerCache | None = None,
) -> RunState:
    run = RunState(id=uuid.uuid4().hex[:12], site=site)
    started, calls_before, hits_before = time.time(), q.calls, q.cache_hits
    await emit("run", {"run_id": run.id, "site": site.__dict__, "llm": llm.enabled})

    async def step(name: str, label: str, coro):
        await emit("status", {"step": name, "state": "running", "label": label})
        result = await coro
        await emit("status", {"step": name, "state": "done", "label": label})
        return result

    minutes = site.minutes
    try:
        catchment = await step(
            "walk", f"Tracing a {minutes}-minute walk over the street network", walker.walk(site.lat, site.lon, minutes)
        )
        run.catchment = catchment
        await emit("catchment", catchment.public())
        block, (genres, cues), taste = await asyncio.gather(
            step("block", f"Reading every place inside the {minutes}-minute walk", engine.scan_block(q, catchment)),
            step("demand", "Ranking what locals engage with against six same-size areas around",
                 engine.demand_genres(q, catchment)),
            step("taste", "Finding brands and artists this area over-indexes on", engine.local_taste(q, site.lat, site.lon)),
        )
        run.block, run.genres, run.cues, run.taste = block, genres, cues, taste
        run.summary = scoring.summarize_block(block)
        await emit("block", {
            "summary": run.summary,
            "places": [scoring.place_card(p, (site.lat, site.lon)) for p in block],
        })
        await emit("demand", {"genres": genres[:12], "cues": cues})

        await emit("taste", taste)
        gaps = await step(
            "gaps", "Comparing supply with the surroundings and finding places locals love more than the city",
            engine.gap_table(q, catchment, genres, site.focus),
        )
        run.gaps = [with_fit(run, row) for row in gaps]
        await emit("gaps", {"rows": [public_gap(g) for g in run.gaps]})

        if not gaps:
            await emit("concepts", {"concepts": [], "mode": "none", "note": "Not enough Qloo data around this site."})
        else:
            await emit("status", {"step": "concepts", "state": "running", "label": "Designing concepts from the gaps"})
            concepts, mode, about = [], "rules", {}
            if llm.enabled:
                concepts, about = await concepts_from_agent(llm, q, run, emit, answers)
                mode = "agent" if concepts else "rules"
            if not concepts:
                concepts, mode, about = rule_concepts(run), "rules", {}
            if not concepts:
                mode, about = "none", {"note": "None of the categories the block is missing fits this unit."}
            run.concepts = concepts
            await emit("status", {"step": "concepts", "state": "done", "label": "Designing concepts from the gaps"})
            await emit("concepts", {"concepts": concepts, "mode": mode, **about})
    except QlooError as exc:
        await emit("error", {"message": str(exc)})
    finally:
        store.add(run)
        await emit("done", {
            "run_id": run.id,
            "seconds": round(time.time() - started, 1),
            "qloo_calls": q.calls - calls_before,
            "cache_hits": q.cache_hits - hits_before,
        })
    return run
