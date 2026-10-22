"""The paid features, plugged into the app: the $19 launch kit and founding-supporter pledge campaigns, with PayPal.

install() adds their endpoints and pages, their part of /api/config and of My places, the answers that carry more than
a detail (commerce.Problem), and PayPal's and the scheduler's callbacks to the paths the origin check lets through.
running() gives them their stores and background work for the app's lifetime. The accounts code knows nothing of them.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request

from . import commerce
from .config import settings
from .db.campaigns import CampaignStore
from .db.events import EventStore
from .db.kits import KitStore
from .payments import pledges
from .payments.paypal import money
from .ratelimit import RateLimiter
from .routes import campaigns, hooks, kits
from .settlement import Settler

CHECKOUTS_PER_HOUR = 20
PLEDGES_PER_HOUR = 20
DRAFTS_PER_HOUR = 20
# How often campaigns past their close are settled, besides the scheduled call to /api/cron/settle.
SETTLE_EVERY_S = 60.0
SHUTDOWN_GRACE_S = 10
PLACES = 100
# Called by PayPal and a scheduled job, never by a page; each proves itself otherwise.
CALLBACKS = frozenset({"/api/paypal/webhook", "/api/cron/settle"})
# The web app's pages for a kit, its printable dossier and a pledge campaign.
PAGES = ("/k/{key}", "/k/{key}/dossier", "/p/{key}")


def paypal_config(request: Request) -> dict:
    """The page's PayPal settings: whether PayPal takes payments, and what the JS SDK and the price need."""
    paypal = request.app.state.services.paypal
    enabled = paypal is not None and paypal.configured
    currency = settings.kit_currency.upper()
    return {"paypal": {
        "enabled": enabled,
        "client_id": settings.paypal_client_id if enabled else None,
        "environment": "live" if settings.paypal_env == "live" else "sandbox",
        "currency": currency,
        "kit_price": money(settings.kit_price, currency),
    }}


async def purchases(request: Request, user: dict, now: datetime) -> dict:
    """The user's kits and pledge campaigns for My places, newest first, at most 100 of each."""
    state = request.app.state
    owned_kits = await state.kits.owned_by(user["id"], PLACES)
    owned = await state.campaigns.owned_by(user["id"], PLACES)
    held = defaultdict(list)
    for row in await state.campaigns.pledges(campaign["id"] for campaign in owned):
        held[row["campaign_id"]].append(row)

    def supporters(row: dict) -> int:
        found = [commerce.pledge_of(pledge, row["currency"]) for pledge in held[row["id"]]]
        return pledges.progress(commerce.campaign_of(row), found, now)["supporters"]

    return {
        "kits": [{
            "token": row["token"], "survey_id": row["survey_id"], "index": row["idx"], "name": row["name"] or "",
            "status": row["status"], "created_at": commerce.iso(row["created_at"]), "url": f"/k/{row['token']}",
        } for row in owned_kits],
        "campaigns": [{
            "id": row["id"], "title": row["title"], "status": commerce.public_status(row["status"]),
            "supporters": supporters(row), "goal": row["goal_count"], "deadline": commerce.iso(row["deadline"]),
            "url": f"/p/{row['id']}",
        } for row in owned],
    }


def install(app: FastAPI, page: Callable) -> None:
    """Adds the paid endpoints and pages (served by `page`, the web app's index) to the app."""
    for area in (kits, campaigns, hooks):
        app.include_router(area.router)
    for path in PAGES:
        app.add_api_route(path, page, include_in_schema=False)
    app.add_exception_handler(commerce.Problem, commerce.problem_response)
    app.state.config_parts.append(paypal_config)
    app.state.places_parts.append(purchases)
    app.state.origin_exempt |= CALLBACKS


@asynccontextmanager
async def running(app: FastAPI, settle_every: float | None) -> AsyncIterator[None]:
    """The paid features' stores and background work while the app runs: kits a restart cut off are built again, and
    campaigns past their close settle every `settle_every` seconds (None: never; tests settle by hand)."""
    state = app.state
    state.kits = KitStore(state.db)
    state.campaigns = CampaignStore(state.db)
    state.events = EventStore(state.db)
    state.builder = commerce.KitBuilder(state.kits, state.runs, state.surveys, state.services)
    state.settler = Settler(state.campaigns, state.services.paypal, lambda: state.now())
    state.campaign_lock = asyncio.Lock()
    state.checkout_limiter = RateLimiter(CHECKOUTS_PER_HOUR, 3600)
    state.pledge_limiter = RateLimiter(PLEDGES_PER_HOUR, 3600)
    state.draft_limiter = RateLimiter(DRAFTS_PER_HOUR, 3600)
    await state.builder.resume()
    if settle_every:
        state.settler.start(settle_every)
    try:
        yield
    finally:
        await state.settler.stop(SHUTDOWN_GRACE_S)
        await state.builder.stop()
