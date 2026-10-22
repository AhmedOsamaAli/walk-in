"""Founding-supporter campaigns. The owner of a kit drafts and starts one; neighbors pledge with PayPal (an AUTHORIZE
order, so the money is only held) and may withdraw while it runs; it settles when it closes (app.settlement)."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from .. import auth
from ..commerce import (
    Problem,
    campaign_of,
    designed,
    iso,
    minor,
    paypal_client,
    paypal_problem,
    pledge_custom_id,
    pledge_of,
    public_progress,
    public_status,
)
from ..config import settings
from ..payments import pledges
from ..payments.paypal import RESOURCE_ID, PayPalError, authorized_in_full, request_key
from ..ratelimit import client_ip
from ..survey.concepts import place_names
from ..survey.models import RunState

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")
CAMPAIGN_ID = r"^[A-Za-z0-9_-]{1,32}$"
PAYPAL_ID = r"^[A-Za-z0-9_-]{1,64}$"


class Terms(BaseModel):
    """The owner's terms. They are checked by pledges.validate_campaign, which says what is wrong in plain words."""

    kit_token: str = Field(..., min_length=1, max_length=64)
    amount: Any = Field(None, description='Each pledge, such as "25.00"')
    goal: Any = Field(None, description="Supporters needed")
    deadline: Any = Field(None, description="ISO 8601 with a time zone, at most 27 days away")
    discount: Any = Field(None, description="What founding supporters get off, in the owner's words, or null")


class NewCampaign(Terms):
    title: Any = None
    pitch: Any = None
    perks: Any = None


class Withdrawal(BaseModel):
    token: str = Field(..., min_length=1, max_length=128)


def currency() -> str:
    return settings.kit_currency.upper()


def deadline_of(value: Any) -> Any:
    """An ISO 8601 deadline as a datetime; anything else is left for validate_campaign to explain."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            return value
    return value


def discount_of(value: Any) -> str | None:
    """The owner's discount with its spacing tidied, or None."""
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None


def check_terms(body: Terms, now: datetime) -> tuple[Any, list[str]]:
    deadline = deadline_of(body.deadline)
    problems = pledges.validate_campaign(body.amount, body.goal, deadline, now, currency())
    discount = body.discount
    if discount is not None and (not isinstance(discount, str) or len(" ".join(discount.split())) > pledges.PERK_LIMIT):
        problems.append(f"Write the discount in at most {pledges.PERK_LIMIT} characters: it leads the perks.")
    return deadline, problems


async def kit_for_campaign(request: Request, token: str, user: dict) -> tuple[dict, RunState, dict]:
    """The owner's ready kit, its survey and the concept's design sheet."""
    state = request.app.state
    kit = await state.kits.kit(token)
    if kit is None:
        raise HTTPException(404, "Kit not found.")
    if kit["user_id"] != user["id"]:
        raise HTTPException(403, "Only the kit's owner can start its campaign.")
    if kit["status"] == "refunded":
        raise HTTPException(409, "This kit was refunded.")
    if kit["status"] != "ready":
        raise HTTPException(409, "Start a campaign once the kit is ready.")
    run = await state.runs.fetch(kit["survey_id"])
    if run is None or not 0 <= kit["idx"] < len(run.concepts):
        raise HTTPException(409, "The survey behind this kit is no longer saved.")
    return kit, run, await designed(state.services, state.surveys, run, kit["idx"])


async def campaign_row(request: Request, campaign_id: str) -> dict:
    row = await request.app.state.campaigns.get(campaign_id)
    if row is None:
        raise HTTPException(404, "Campaign not found.")
    return row


async def owners_campaign(request: Request, campaign_id: str, user: dict) -> dict:
    row = await campaign_row(request, campaign_id)
    if row["user_id"] != user["id"]:
        raise HTTPException(403, "Only the campaign's owner can do that.")
    return row


async def progress_now(request: Request, row: dict, at: datetime | None = None) -> dict:
    found = [pledge_of(pledge, row["currency"]) for pledge in await request.app.state.campaigns.pledges([row["id"]])]
    return pledges.progress(campaign_of(row), found, at or request.app.state.now())


async def campaign_view(request: Request, row: dict) -> dict:
    """The pledge page: the campaign, its progress, and for its owner the pledges by status and the settlement report."""
    user = await auth.current_user(request)
    now = request.app.state.now()
    campaign = campaign_of(row)
    progress = await progress_now(request, row, now)
    offer = row["offer"] or {}
    owner = user is not None and user["id"] == row["user_id"]
    view = {
        "id": row["id"],
        "status": public_status(row["status"]),
        "accepting": pledges.accepting(campaign, now),
        "name": offer.get("name") or "",
        "neighborhood": offer.get("neighborhood"),
        "concept": offer.get("concept") or {"genre": "", "summary": ""},
        "title": row["title"],
        "pitch": offer.get("pitch") or "",
        "perks": offer.get("perks") or [],
        "how_it_works": offer.get("how_it_works") or "",
        "amount": campaign.amount,
        "currency": campaign.currency,
        "goal": campaign.goal,
        "deadline": iso(campaign.deadline),
        "closed_at": iso(campaign.closed_at),
        "progress": public_progress(progress),
        "is_owner": owner,
        "survey_url": f"/s/{row['survey_id']}?sheet={row['idx']}",
    }
    if owner:
        view["owner"] = {"counts": progress["counts"], "report": row["report"]}
    return view


@router.post("/campaigns/draft")
async def draft(request: Request, body: Terms, user: auth.SignedIn) -> dict:
    """The campaign page drafted from the kit's concept: the owner's terms go in unchanged."""
    state = request.app.state
    kit, run, sheet = await kit_for_campaign(request, body.kit_token, user)
    deadline, problems = check_terms(body, state.now())
    if problems:
        return {"title": "", "pitch": "", "perks": [], "how_it_works": "", "problems": problems}
    if not state.draft_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many drafts from this address. Try again later.")
    services = state.services
    offer = await pledges.draft_offer(
        services.llm, sheet, amount=body.amount, goal=body.goal, deadline=deadline, currency=currency(),
        discount=discount_of(body.discount), concept=run.concepts[kit["idx"]], avoid=place_names(run), answers=services.answers,
    )
    return {key: offer[key] for key in ("title", "pitch", "perks", "how_it_works")} | {"problems": []}


@router.post("/campaigns")
async def create(request: Request, body: NewCampaign, user: auth.SignedIn) -> dict:
    """Starts the campaign on the owner's terms and words, once both keep the rules; one running campaign per kit."""
    state = request.app.state
    kit, run, sheet = await kit_for_campaign(request, body.kit_token, user)
    running = await state.campaigns.for_kit(kit["token"], active=True)
    if running:
        raise Problem(409, "This kit already has a campaign running.", url=f"/p/{running['id']}")
    now = state.now()
    deadline, problems = check_terms(body, now)
    if problems:
        raise Problem(422, " ".join(problems), problems=problems)
    concept, avoid, discount = run.concepts[kit["idx"]], place_names(run), discount_of(body.discount)
    terms = {"amount": body.amount, "goal": body.goal, "deadline": deadline, "currency": currency(), "discount": discount,
             "concept": concept, "avoid": avoid}
    problems = pledges.offer_problems(sheet, title=body.title, pitch=body.pitch, perks=body.perks, **terms)
    if problems:
        raise Problem(422, " ".join(problems), problems=problems)
    # The fixed explanation of the hold, as the draft gives it (the rules write it; no model is asked).
    how_it_works = (await pledges.draft_offer(None, sheet, **terms))["how_it_works"]
    campaign = pledges.new_campaign(uuid.uuid4().hex[:16], body.amount, body.goal, deadline, now, currency())
    where = (sheet.get("launch") or {}).get("where") or {}
    hoods = [hood for hood in where.get("neighborhoods") or [] if isinstance(hood, str) and hood.strip()]
    offer = {
        "pitch": " ".join(body.pitch.split()),
        "perks": [" ".join(perk.split()) for perk in body.perks],
        "how_it_works": how_it_works,
        "discount": discount,
        "name": kit["name"] or "",
        "neighborhood": hoods[0] if hoods else None,
        "concept": {"genre": concept.get("genre") or "", "summary": concept.get("one_liner") or sheet.get("tagline") or ""},
    }
    async with state.campaign_lock:
        running = await state.campaigns.for_kit(kit["token"], active=True)
        if running:
            raise Problem(409, "This kit already has a campaign running.", url=f"/p/{running['id']}")
        await state.campaigns.create(
            id=campaign.id, survey_id=kit["survey_id"], idx=kit["idx"], user_id=user["id"], kit_token=kit["token"],
            title=" ".join(body.title.split()), offer=offer, amount_cents=minor(campaign.amount, campaign.currency),
            currency=campaign.currency, goal_count=campaign.goal, deadline=campaign.deadline, status="open",
        )
    return {"id": campaign.id, "url": f"/p/{campaign.id}"}


@router.get("/campaigns/{campaign_id}")
async def campaign_page(request: Request, campaign_id: str = Path(..., pattern=CAMPAIGN_ID)) -> dict:
    return await campaign_view(request, await campaign_row(request, campaign_id))


@router.post("/campaigns/{campaign_id}/pledges")
async def pledge(request: Request, campaign_id: str = Path(..., pattern=CAMPAIGN_ID)) -> dict:
    """A PayPal order that will hold one supporter's pledge, for the page's PayPal buttons to approve."""
    state = request.app.state
    row = await campaign_row(request, campaign_id)
    campaign = campaign_of(row)
    if not pledges.accepting(campaign, state.now()):
        raise HTTPException(409, "This campaign no longer takes pledges.")
    if not state.pledge_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many pledges from this address. Try again later.")
    client = paypal_client(request)
    pledge_id = uuid.uuid4().hex
    name = (row["offer"] or {}).get("name") or row["title"]
    try:
        order = await client.create_order(
            intent="AUTHORIZE", amount=campaign.amount, currency=campaign.currency,
            description=f"Founding supporter pledge: {name}", custom_id=pledge_custom_id(campaign_id, pledge_id),
            reference_id=campaign_id, request_id=str(uuid.uuid4()),
        )
    except PayPalError as exc:
        raise paypal_problem(exc, "start the pledge") from exc
    order_id = order.get("id")
    if not isinstance(order_id, str) or not RESOURCE_ID.match(order_id):
        raise HTTPException(502, "PayPal did not return an order. Try again in a moment.")
    await state.campaigns.add_pledge(
        id=pledge_id, campaign_id=campaign_id, order_id=order_id, amount_cents=row["amount_cents"], status="created",
    )
    return {"order_id": order_id}


@router.post("/campaigns/{campaign_id}/pledges/{order_id}/authorize")
async def authorize(
    request: Request, campaign_id: str = Path(..., pattern=CAMPAIGN_ID), order_id: str = Path(..., pattern=PAYPAL_ID),
) -> dict:
    """Holds an approved pledge and counts it; the answer carries the supporter's private link to withdraw it."""
    state = request.app.state
    row = await campaign_row(request, campaign_id)
    found = await state.campaigns.pledge(campaign_id=campaign_id, order_id=order_id)
    if found is None:
        raise HTTPException(404, "Pledge not found.")
    if found["status"] != "created":
        raise HTTPException(409, "This pledge was already handled. Use the withdraw link you were given to change it.")
    campaign = campaign_of(row)
    if not pledges.accepting(campaign, state.now()):
        raise HTTPException(409, "This campaign no longer takes pledges, so nothing was held.")
    client = paypal_client(request)
    try:
        # A fresh request id each time, so a supporter whose card was declined can retry with another (see kits.capture).
        held = await client.authorize_order(order_id, str(uuid.uuid4()))
    except PayPalError as exc:
        if not exc.has("ORDER_ALREADY_AUTHORIZED"):
            raise paypal_problem(exc, "hold the pledge") from exc
        try:
            held = await client.get_order(order_id)
        except PayPalError as again:
            raise paypal_problem(again, "confirm the pledge") from again
    hold = pledges.pledge_from_order(found["id"], held)
    if not authorized_in_full(held, campaign.amount, campaign.currency, pledge_custom_id(campaign_id, found["id"])):
        if hold.status == pledges.PledgeStatus.DECLINED:
            await state.campaigns.update_pledge(
                found["id"], only=("created",), status="declined", authorization_id=hold.authorization_id,
                payer_id=hold.payer_id,
            )
            raise Problem(402, "PayPal would not hold this payment, so nothing was pledged. Try another way to pay.", retry=False)
        if hold.status == pledges.PledgeStatus.CREATED:
            raise Problem(409, "PayPal is still reviewing this pledge. It counts once PayPal confirms the hold.", pending=True)
        log.error("Pledge order %s was held but not as pledged: %s", order_id, hold)
        raise HTTPException(502, "PayPal's answer did not match this pledge, so it was not counted.")
    token = auth.new_token()
    now = state.now()
    stored = await state.campaigns.update_pledge(
        found["id"], only=("created",), status="authorized", authorization_id=hold.authorization_id,
        payer_id=hold.payer_id, authorized_at=hold.authorized_at or now, expires_at=hold.expires_at,
        withdraw_token_hash=auth.token_hash(token),
    )
    if not stored:
        raise HTTPException(409, "This pledge was already handled.")
    # PayPal's clock may run a little ahead of ours; the new hold counts from the moment PayPal placed it.
    progress = await progress_now(request, row, max(now, hold.authorized_at or now))
    return {
        "status": "authorized",
        "supporter_number": progress["supporters"],
        "withdraw_url": f"/p/{campaign_id}?withdraw={token}",
        "progress": public_progress(progress),
    }


@router.post("/campaigns/{campaign_id}/withdraw")
async def withdraw(request: Request, body: Withdrawal, campaign_id: str = Path(..., pattern=CAMPAIGN_ID)) -> dict:
    """Releases a supporter's hold while the campaign still takes pledges; the token is from their withdraw link."""
    state = request.app.state
    await campaign_row(request, campaign_id)
    found = await state.campaigns.pledge(campaign_id=campaign_id, withdraw_token_hash=auth.token_hash(body.token))
    if found is None:
        raise HTTPException(404, "That withdraw link is not valid for this campaign.")
    client = paypal_client(request)
    async with state.settler.lock:  # never while a settlement collects it
        row = await campaign_row(request, campaign_id)
        found = await state.campaigns.pledge(id=found["id"])
        if found["status"] == "authorized":
            if not pledges.accepting(campaign_of(row), state.now()):
                raise HTTPException(409, "The campaign has closed, so pledges can no longer be withdrawn.")
            original = found["authorization_id"]
            if original:
                try:
                    await client.void_authorization(original, request_key("void", original))
                except PayPalError as exc:
                    if not exc.has(*pledges.VOIDED_ISSUES):
                        raise paypal_problem(exc, "release the pledge") from exc
            await state.campaigns.update_pledge(found["id"], only=("authorized",), status="voided", error=None)
        elif found["status"] != "voided":
            raise HTTPException(409, "This pledge can no longer be withdrawn.")
        progress = await progress_now(request, row)
    return {"status": "voided", "progress": public_progress(progress)}


@router.post("/campaigns/{campaign_id}/close")
async def close(request: Request, user: auth.SignedIn, campaign_id: str = Path(..., pattern=CAMPAIGN_ID)) -> dict:
    """Closes the campaign now and settles it at once: every hold collected if it met its goal, released if not."""
    await owners_campaign(request, campaign_id, user)
    await request.app.state.settler.close(campaign_id)
    return await campaign_view(request, await campaign_row(request, campaign_id))


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel(request: Request, user: auth.SignedIn, campaign_id: str = Path(..., pattern=CAMPAIGN_ID)) -> dict:
    """Ends the campaign and releases every hold, whatever the count, unless it already met its goal and collects."""
    row = await owners_campaign(request, campaign_id, user)
    if row["status"] in ("funded", "partial", "collected") or row["funded"]:
        raise HTTPException(409, "This campaign met its goal and collects the pledges, so it can no longer be cancelled.")
    await request.app.state.settler.close(campaign_id, cancel=True)
    return await campaign_view(request, await campaign_row(request, campaign_id))
