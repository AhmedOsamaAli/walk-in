"""Finished surveys anyone can open before running a survey of their own: what Walk-in gives, before it is asked for.

The examples are surveys already saved (settings.examples lists their ids). Opening one replays its saved events, and
its launch kit and report are already built, so looking spends no Qloo or AI quota.
"""
from __future__ import annotations

import logging
import re
import time

from fastapi import APIRouter, Request

from .. import schemas
from ..config import settings
from .kits import kit_url

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")

RUN_ID = re.compile(r"^[A-Za-z0-9-]{1,32}$")
FRESH_S = 600  # how long the list is kept: the surveys behind it do not change
RETRY_S = 30  # how soon it is read again after the database failed


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
async def examples(request: Request) -> list[dict]:
    """The finished surveys anyone can open, in the order configured; none when none is configured or saved."""
    ids = tuple(run_id for run_id in settings.examples if RUN_ID.match(run_id))
    if not ids:
        return []
    state = request.app.state
    cache: dict = state.examples_cache
    now = time.monotonic()
    if ids in cache and now < cache[ids][0]:
        return cache[ids][1]
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
    cache[ids] = (now + (RETRY_S if failed else FRESH_S), found)
    return found
