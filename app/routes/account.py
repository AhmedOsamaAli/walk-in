"""Public settings, sign-in (Google, or a development login), sign-out, the signed-in user, My places (with the user's
campaigns) and deleting the account."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import auth, cache_policy
from ..config import settings
from ..db.surveys import survey_status
from ..payments import founders
from ..payments.records import progress_of
from ..ratelimit import client_ip

router = APIRouter(prefix="/api")
PLACES = 100


class GoogleSignIn(BaseModel):
    credential: str = Field(..., max_length=8192, description="The ID token Google Identity Services handed the page")


class DevSignIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    name: str = Field("", max_length=200)


def iso(moment: datetime) -> str:
    """A time as the API writes it: ISO 8601 in UTC, to the second ('2026-10-22T14:03:00Z')."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def limit_sign_ins(request: Request) -> None:
    if not request.app.state.auth_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many sign-in attempts from this address. Try again later.")


@router.get("/config")
async def public_config(request: Request, response: Response) -> dict:
    """What the web app needs to know before anyone signs in: how to sign in, whether pledging with PayPal works here
    (and what PayPal's JavaScript SDK needs), and whether new surveys are paused. All of it changes only with a deploy,
    so the front door may keep it (cache_policy.STATIC)."""
    response.headers["Cache-Control"] = cache_policy.STATIC
    return {
        "google_client_id": settings.google_client_id or None,
        "dev_login": settings.dev_login,
        "paypal": founders.paypal_config(request.app.state),
        "surveys_paused": settings.surveys_paused,
    }


@router.post("/auth/google")
async def google_sign_in(request: Request, body: GoogleSignIn) -> dict:
    if not settings.google_client_id:
        raise HTTPException(503, "Google sign-in is not set up on this server.")
    limit_sign_ins(request)
    try:
        claims = await auth.verify_google_token(body.credential, settings.google_client_id, request.app.state.services.google)
    except auth.TokenError as exc:
        raise HTTPException(400, str(exc)) from exc
    except auth.KeysUnavailable as exc:
        raise HTTPException(503, "Google sign-in is unavailable right now. Try again in a minute.") from exc
    email = claims["email"]
    name = str(claims.get("name") or "").strip() or email.split("@")[0]
    picture = claims.get("picture") if isinstance(claims.get("picture"), str) else None
    user = await request.app.state.accounts.sign_in(f"google:{claims['sub']}", email, name, picture)
    await auth.start_session(request, user)
    return {"user": auth.public_user(user)}


@router.post("/auth/dev")
async def dev_sign_in(request: Request, body: DevSignIn) -> dict:
    """Signs in with any email, for development only: never when PUBLIC_URL is https."""
    if not settings.dev_login:
        raise HTTPException(404, "Not Found")
    limit_sign_ins(request)
    email = body.email.strip().lower()
    if "@" not in email.strip("@") or any(char.isspace() for char in email):
        raise HTTPException(400, "Give an email address.")
    name = body.name.strip() or email.split("@")[0]
    user = await request.app.state.accounts.sign_in(f"dev:{email}", email, name, None)
    await auth.start_session(request, user)
    return {"user": auth.public_user(user)}


@router.post("/auth/logout", status_code=204)
async def sign_out(request: Request) -> Response:
    await auth.end_session(request)
    return Response(status_code=204)


@router.get("/me")
async def me(request: Request) -> dict:
    """The signed-in user, or null: never 401, so the page can ask on every load."""
    user = await auth.current_user(request)
    return {"user": auth.public_user(user) if user else None}


@router.delete("/me", status_code=204)
async def delete_me(request: Request, user: auth.SignedIn) -> Response:
    """Deletes the account: the user, all their sessions (on every device) and the surveys in their My places, with
    their design sheets. This browser forgets its session and its device id."""
    await auth.delete_account(request, user)
    return Response(status_code=204)


@router.get("/me/places")
async def places(request: Request, user: auth.SignedIn) -> dict:
    """The user's surveys, the launch kits made for them and the campaigns the user started, newest first, at most 100
    of each."""
    state = request.app.state
    now = state.now()
    surveys = await state.accounts.surveys(user["id"], PLACES)
    kits = await state.kits.owned_by(user["id"], PLACES)
    campaigns = await state.campaigns.owned_by(user["id"], PLACES)
    held: dict[str, list[dict]] = {row["id"]: [] for row in campaigns}
    for pledge in await state.campaigns.pledges(held):
        held[pledge["campaign_id"]].append(pledge)
    return {
        "surveys": [{
            "id": row["id"], "label": row["label"], "intent": row["intent"],
            "status": survey_status(row["status"], row["created_at"], now), "created_at": iso(row["created_at"]),
            "headline": row["headline"], "url": f"/s/{row['id']}",
        } for row in surveys],
        "kits": [{
            "token": row["token"], "survey_id": row["survey_id"], "index": row["idx"], "name": row["name"] or "",
            "status": row["status"], "created_at": iso(row["created_at"]), "url": f"/k/{row['token']}",
        } for row in kits],
        "campaigns": [{
            "id": row["id"], "title": row["title"], "status": row["status"],
            "supporters": progress_of(row, held[row["id"]], now)["supporters"], "goal": row["goal_count"],
            "deadline": iso(row["deadline"]), "url": f"/p/{row['id']}",
        } for row in campaigns],
    }
