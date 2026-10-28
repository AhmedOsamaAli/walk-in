"""Launch kits (free): one per survey concept, for anyone with the survey, built in the background (app.kits).
Anyone with a kit's link can open it."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Path, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import auth, cache_policy
from ..payments.records import major, progress_of
from ..ratelimit import client_ip
from ..response_cache import Page, page_response
from ..survey import kit as launch_kit
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
async def kit_page(request: Request, token: str = Path(..., pattern=TOKEN)) -> Response:
    """A kit, for anyone with its link; the page asks again while it is building. A kit saved without its street map
    gets it here when it can (app.kits). It is the same for everyone, so memory and the front door may keep it; the
    campaigns started from it are GET /api/kits/{token}/campaigns."""
    page = await kit_page_for(request.app.state, token)
    if page is None:
        raise HTTPException(404, "Kit not found.")
    return page_response(page, cache_policy.for_kit(page.survey_id, page.status, settled=page.settled), request)


async def kit_page_for(state, token: str) -> Page | None:
    """A kit's page as GET /api/kits/{token} sends it, or None when there is no such kit: from memory once it is ready
    with its street map (it never changes again), else from the database."""

    async def read() -> Page | None:
        kit = await state.kits.kit(token)
        if kit is None:
            return None
        kit = await state.builder.with_streets(kit)
        body = page_body(kit_fields(kit))
        final = kit["status"] == "ready" and not launch_kit.lacks_street_map(kit["payload"])
        return Page(body, kit["survey_id"], kit["status"], final=final, settled=not state.builder.fillable(kit))

    return await state.responses.fetch(f"kit:{token}", read)


def page_body(content: dict) -> bytes:
    """The bytes FastAPI's default JSONResponse makes of a route's dict. The kit's payload comes from the database as
    JSON already, so FastAPI's jsonable_encoder would only copy it (55 ms for a 180 KB kit, before rendering it); it
    runs only if something in the page is not JSON."""
    try:
        return JSONResponse(content).body
    except TypeError:
        return JSONResponse(jsonable_encoder(content)).body


def kit_fields(kit: dict) -> dict:
    """What a kit's page is sent: the payload once it is ready, why it failed when it did."""
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


@router.get("/kits/{token}/campaigns")
async def campaigns_for_kit(request: Request, token: str = Path(..., pattern=TOKEN)) -> dict:
    """The Walk-in Founders campaigns started from a kit that still take pledges, the viewer's own first, then the
    newest: the poster's QR code opens the viewer's own. Apart from the kit's page because they change with every pledge
    and depend on who asks, so nothing keeps them (no-store). No such kit has none."""
    return {"campaigns": await kit_campaigns(request, token)}


async def kit_campaigns(request: Request, token: str) -> list[dict]:
    """The kit's campaigns that still take pledges: the viewer's own first, then the newest."""
    state = request.app.state
    now = state.now()
    rows = await state.campaigns.accepting_for_kit(token, now)
    if not rows:
        return []
    user = await auth.current_user(request)
    held: dict[str, list[dict]] = {row["id"]: [] for row in rows}
    for pledge in await state.campaigns.pledges(held):
        held[pledge["campaign_id"]].append(pledge)
    listed = [{
        "id": row["id"], "url": f"/p/{row['id']}", "is_owner": user is not None and row["user_id"] == user["id"],
        "status": row["status"], "amount": major(row["amount_cents"], row["currency"]), "goal": row["goal_count"],
        "supporters": progress_of(row, held[row["id"]], now)["supporters"], "deadline": iso(row["deadline"]),
    } for row in rows]
    return sorted(listed, key=lambda campaign: not campaign["is_owner"])  # stable: the newest first otherwise


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
