"""Launch kits, free for now: one per survey concept, for anyone with the survey, built in the background (app.kits).
Anyone with a kit's link can open it."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from .. import auth
from ..ratelimit import client_ip
from ..survey.dossier import business_name

router = APIRouter(prefix="/api")
TOKEN = r"^[A-Za-z0-9_-]{1,64}$"


class KitRequest(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=32)
    index: int = Field(..., ge=0, le=100)


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def kit_url(token: str) -> str:
    return f"/k/{token}"


def made(kit: dict) -> dict:
    return {"token": kit["token"], "url": kit_url(kit["token"]), "status": kit["status"]}


def limit_builds(request: Request) -> None:
    """New builds call the model many times, so each client and the whole server get only so many."""
    state = request.app.state
    if not state.kit_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many kits from this address. Try again in an hour.")
    if not state.kit_budget.allow():
        raise HTTPException(429, "Today's kits are all made. Try again tomorrow.")


@router.post("/kits")
async def make_kit(request: Request, body: KitRequest) -> dict:
    """The concept's launch kit: the one made before, else a new one, built in the background."""
    state = request.app.state
    run = await state.runs.fetch(body.run_id)
    if run is None or not 0 <= body.index < len(run.concepts):
        raise HTTPException(404, "Survey or concept not found. Run the site again.")
    found = await state.kits.for_concept(body.run_id, body.index)
    if found:
        return made(found)
    # The single point where payment will be added once the kit is sold: a kit comes into being only here, after it is
    # clear that none exists for this concept. Take the payment at this line, before the kit is created and built.
    limit_builds(request)
    name = business_name(run, run.concepts[body.index], run.designs.get(body.index) or {})
    try:
        kit, new = await state.kits.create(body.run_id, body.index, token=auth.new_token(), name=name)
    except LookupError as exc:  # the survey was never saved, or was deleted meanwhile
        raise HTTPException(404, "Survey not found. Run the site again.") from exc
    if new:
        state.builder.start(kit["token"])
    return made(kit)


@router.get("/kits")
async def find_kit(request: Request, run_id: str = Query(..., max_length=32), index: int = Query(..., ge=0, le=100)) -> dict:
    """Whether the concept has a kit already, so the page offers to open it rather than to make it."""
    kit = await request.app.state.kits.for_concept(run_id, index)
    return {"kit_url": kit_url(kit["token"]) if kit else None}


@router.get("/kits/{token}")
async def kit_page(request: Request, token: str = Path(..., pattern=TOKEN)) -> dict:
    """A kit, for anyone with its link; the page asks again while it is building. A kit saved without its street map
    gets it here when it can (app.kits)."""
    kit = await request.app.state.kits.kit(token)
    if kit is None:
        raise HTTPException(404, "Kit not found.")
    kit = await request.app.state.builder.with_streets(kit)
    return {
        "token": kit["token"],
        "status": kit["status"],
        "survey_id": kit["survey_id"],
        "index": kit["idx"],
        "name": kit["name"] or "",
        "created_at": iso(kit["created_at"]),
        "survey_url": f"/s/{kit['survey_id']}?sheet={kit['idx']}",
        "kit": kit["payload"] if kit["status"] == "ready" else None,
        "error": kit["error"] if kit["status"] == "failed" else None,
    }


@router.post("/kits/{token}/retry", status_code=202)
async def retry(request: Request, token: str = Path(..., pattern=TOKEN)) -> dict:
    """Builds a kit that failed again."""
    state = request.app.state
    kit = await state.kits.kit(token, with_payload=False)
    if kit is None:
        raise HTTPException(404, "Kit not found.")
    if kit["status"] != "failed":
        raise HTTPException(409, "Only a kit that failed to build can be built again.")
    limit_builds(request)
    if not await state.kits.rebuild(token):  # another request started it again meanwhile
        raise HTTPException(409, "Only a kit that failed to build can be built again.")
    state.builder.start(token)
    return {**made(kit), "status": "building"}
