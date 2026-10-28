"""Finished surveys anyone can open before running a survey of their own: what Walk-in gives, before it is asked for.

The examples are surveys already saved (settings.examples lists their ids). Opening one replays its saved events, and
its launch kit and report are already built, so looking spends no Qloo or AI quota. The server loads them into memory
as it starts (warm_up), and the list is answered from memory: read again in the background once it is FRESH_S old, so
no visitor waits for the database, and kept as it was while the database fails.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from fastapi import APIRouter, Request, Response

from .. import cache_policy, schemas
from ..config import settings
from .kits import kit_page_for, kit_url
from .surveys import run_page_for

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")

RUN_ID = re.compile(r"^[A-Za-z0-9-]{1,32}$")
FRESH_S = 600  # how long the list is kept before it is read again: only a new kit for an example changes it
RETRY_S = 30  # how soon it is read again after the database failed


def example_ids() -> tuple[str, ...]:
    """The examples configured, in order; malformed ids are left out."""
    return tuple(run_id for run_id in settings.examples if RUN_ID.match(run_id))


async def warm_up(state) -> None:
    """Loads the examples into memory as the server starts, in the background: each one's record, its ready kits and the
    examples list, so the first visitors (judges among them) open them without waiting for the database, which may
    be asleep by then. Never raises; what fails to load is read when it is first opened, as before."""
    started = time.perf_counter()
    ids = example_ids()
    for run_id in ids:
        try:
            await run_page_for(state, run_id)
            for token in await state.kits.ready_for(run_id):
                await kit_page_for(state, token)
        except Exception:
            log.warning("Could not load example %s into memory", run_id, exc_info=True)
    if not ids:
        return
    try:
        await current_list(state, ids)
    except Exception:
        log.warning("Could not read the examples list", exc_info=True)
    log.info("Examples in memory in %.1fs: %s", time.perf_counter() - started, state.responses.stats())


def example_of(row: dict) -> dict | None:
    """What a saved survey shows as an example: its site, area, age focus and results; None unless it ran to its end."""
    if row.get("status") != "complete":
        return None
    # Each event as last streamed (a survey streams many status events, and one of each of the others).
    events = {event[0]: event[1] for event in row.get("events") or [] if len(event) >= 2 and isinstance(event[1], dict)}
    started = events.get("run") or {}
    site = started.get("site") if isinstance(started.get("site"), dict) else {}
    catchment = events.get("catchment") or {}
    area = started.get("area_label") or catchment.get("label") or f"{site.get('minutes') or 10}-minute walk"
    concepts = [c["name"] for c in (events.get("concepts") or {}).get("concepts") or []
                if isinstance(c, dict) and isinstance(c.get("name"), str)]
    gaps = [r for r in (events.get("gaps") or {}).get("rows") or [] if isinstance(r, dict)]
    verdict = events.get("verdict") or {}
    return {
        "run_id": row["id"],
        "url": f"/s/{row['id']}",
        "label": row.get("label") or site.get("label") or "A storefront",
        "intent": row.get("intent") or site.get("intent") or "explore",
        "business": site.get("business") or None,
        "area": area,
        "ages": started.get("ages_label"),
        "llm": bool(started.get("llm")),
        "headline": row.get("headline"),
        "verdict": verdict.get("headline") if isinstance(verdict.get("headline"), str) else None,
        "concepts": concepts[:4],
        "gaps": len(gaps),
        "top_gaps": [r["genre"] for r in gaps[:3] if isinstance(r.get("genre"), str)],
        "kit": None,
    }


async def ready_kit(kits, run_id: str, concepts: int) -> dict | None:
    """The first of the survey's concepts whose launch kit is built, with the links to it and its report."""
    for index in range(max(concepts, 1)):
        kit = await kits.for_concept(run_id, index)
        if kit and kit["status"] == "ready":
            url = kit_url(kit["token"])
            return {"token": kit["token"], "index": index, "name": kit.get("name"), "url": url,
                    "report_url": f"{url}/dossier"}
    return None


@router.get("/examples", response_model=list[schemas.Example])
async def examples(request: Request, response: Response) -> list[dict]:
    """The finished surveys anyone can open, in the order configured; none when none is configured or saved. A list
    read while the database failed is kept here for a little while only, and nowhere else."""
    ids = example_ids()
    response.headers["Cache-Control"] = cache_policy.EXAMPLES
    if not ids:
        return []
    found, failed = await current_list(request.app.state, ids)
    if failed:
        response.headers["Cache-Control"] = cache_policy.NO_STORE
    return found


async def current_list(state, ids: tuple[str, ...]) -> tuple[list[dict], bool]:
    """The examples list and whether the database failed while it was read: from memory, read again in the background
    once it is old (FRESH_S, or RETRY_S after a failure); the first time, read now. One read at a time."""
    entry = state.examples_cache.get(ids)
    reading = state.examples_reading.get(ids)
    if reading is None or reading.done():
        if entry is not None and time.monotonic() < entry[0]:
            return entry[1], entry[2]
        reading = state.examples_reading[ids] = asyncio.create_task(refresh(state, ids))
    if entry is not None:
        return entry[1], entry[2]
    return await asyncio.shield(reading)


async def refresh(state, ids: tuple[str, ...]) -> tuple[list[dict], bool]:
    """Reads the list again; when the database fails, a good list read before stays (the examples do not change)."""
    found, failed = await read_examples(state, ids)
    before = state.examples_cache.get(ids)
    if failed and before is not None and not before[2]:
        found, failed = before[1], False
        state.examples_cache[ids] = (time.monotonic() + RETRY_S, found, failed)
    else:
        state.examples_cache[ids] = (time.monotonic() + (RETRY_S if failed else FRESH_S), found, failed)
    return found, failed


async def read_examples(state, ids: tuple[str, ...]) -> tuple[list[dict], bool]:
    """The examples saved among `ids`, with their kits, and whether the database failed meanwhile."""
    found, failed = [], False
    for run_id in ids:
        try:
            row = await state.surveys.get(run_id, with_state=False)
            example = example_of(row) if row else None
            if example:
                example["kit"] = await ready_kit(state.kits, run_id, len(example["concepts"]))
                found.append(example)
        except Exception:  # the database is down: the first screen still loads, without examples for now
            failed = True
            log.warning("Could not read example survey %s", run_id, exc_info=True)
    return found, failed
