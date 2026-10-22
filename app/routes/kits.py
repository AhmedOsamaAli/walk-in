"""The $19 launch kit: buying it with PayPal (a CAPTURE order), its page, building it again and refunding it."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from .. import auth
from ..commerce import (
    Problem,
    iso,
    kit_custom_id,
    major,
    minor,
    paypal_client,
    paypal_problem,
)
from ..config import settings
from ..payments.paypal import (
    RESOURCE_ID,
    PayPalError,
    money,
    paid_in_full,
    request_key,
    summarize_capture,
)
from ..ratelimit import client_ip
from ..survey.dossier import business_name

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")
PAYPAL_ID = r"^[A-Za-z0-9_-]{1,64}$"
TOKEN = r"^[A-Za-z0-9_-]{1,64}$"


class Checkout(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=32)
    index: int = Field(..., ge=0, le=100)


def kit_url(token: str) -> str:
    return f"/k/{token}"


def already_owned(kit: dict) -> Problem:
    return Problem(409, "You already own the launch kit for this concept.", kit_url=kit_url(kit["token"]))


@router.get("/kits/mine")
async def my_kit(
    request: Request,
    user: auth.SignedIn,
    run_id: str = Query(..., max_length=32),
    index: int = Query(..., ge=0, le=100),
) -> dict:
    """Whether the user already owns the kit for this concept, so the page offers to open it instead of selling it."""
    kit = await request.app.state.kits.owned(user["id"], run_id, index)
    return {"kit_url": kit_url(kit["token"]) if kit else None}


@router.post("/checkout")
async def checkout(request: Request, body: Checkout, user: auth.SignedIn) -> dict:
    """A PayPal order for the kit of one concept, for the page's PayPal buttons to approve."""
    state = request.app.state
    client = paypal_client(request)
    run = await state.runs.fetch(body.run_id)
    if run is None or not 0 <= body.index < len(run.concepts):
        raise HTTPException(404, "Survey or concept not found. Run the site again.")
    owned = await state.kits.owned(user["id"], body.run_id, body.index)
    if owned:
        raise already_owned(owned)
    if not state.checkout_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many checkouts from this address. Try again later.")
    currency = settings.kit_currency.upper()
    price = money(settings.kit_price, currency)
    name = business_name(run, run.concepts[body.index], run.designs.get(body.index) or {})
    try:
        order = await client.create_order(
            intent="CAPTURE", amount=price, currency=currency, description=f"Walk-in launch kit: {name}",
            custom_id=kit_custom_id(user["id"], body.run_id, body.index), request_id=str(uuid.uuid4()),
        )
    except PayPalError as exc:
        raise paypal_problem(exc, "start the payment") from exc
    order_id = order.get("id")
    if not isinstance(order_id, str) or not RESOURCE_ID.match(order_id):
        raise HTTPException(502, "PayPal did not return an order. Try again in a moment.")
    try:
        await state.kits.add_order(
            order_id=order_id, user_id=user["id"], survey_id=body.run_id, idx=body.index, amount_cents=minor(price, currency),
            currency=currency, environment="live" if settings.paypal_env == "live" else "sandbox",
        )
    except IntegrityError as exc:  # the survey was never saved
        raise HTTPException(404, "Survey not found. Run the site again.") from exc
    return {"order_id": order_id}


@router.post("/checkout/{order_id}/capture")
async def capture(request: Request, user: auth.SignedIn, order_id: str = Path(..., pattern=PAYPAL_ID)) -> dict:
    """Collects an approved kit order and starts building the kit. Capturing again answers with the same kit."""
    state = request.app.state
    order = await state.kits.order(order_id)
    if order is None or order["product"] != "launch_kit" or order["user_id"] != user["id"]:
        raise HTTPException(404, "Order not found.")
    kit = await state.kits.kit_for_order(order_id)
    if kit:
        return {"token": kit["token"], "kit_url": kit_url(kit["token"])}
    if order["status"] not in ("created", "pending"):
        raise HTTPException(409, "This order can no longer be paid. Start again from the concept.")
    owned = await state.kits.owned(user["id"], order["survey_id"], order["idx"])
    if owned:
        raise already_owned(owned)
    client = paypal_client(request)
    try:
        # A fresh request id each time: after a declined card the buyer retries with another, and PayPal would answer
        # a repeated id with the decline again. An order is never captured twice either way.
        paid = await client.capture_order(order_id, str(uuid.uuid4()))
    except PayPalError as exc:
        if not exc.has("ORDER_ALREADY_CAPTURED"):
            raise paypal_problem(exc, "take the payment") from exc
        try:
            paid = await client.get_order(order_id)
        except PayPalError as again:
            raise paypal_problem(again, "confirm the payment") from again
    return await settle_order(request.app.state, order, paid)


async def settle_order(state, order: dict, paid: dict) -> dict:
    """Delivers the kit for a captured order once PayPal's answer shows it paid exactly as sold; otherwise records why
    not and answers as the page needs (402 to choose another way to pay, 409 while PayPal reviews the payment)."""
    facts = summarize_capture(paid)
    currency = order["currency"]
    custom_id = kit_custom_id(order["user_id"], order["survey_id"], order["idx"])
    if paid_in_full(paid, major(order["amount_cents"], currency), currency, custom_id):
        kit = await deliver(state, order, facts["capture_id"], facts["payer_id"])
        return {"token": kit["token"], "kit_url": kit_url(kit["token"])}
    found = {"capture_id": facts["capture_id"], "payer_id": facts["payer_id"]}
    if facts["capture_status"] == "PENDING":
        await state.kits.mark_order(order["id"], "pending", unless=("completed", "refunded"), **found)
        raise Problem(
            409, "PayPal is still reviewing this payment. Your kit is built as soon as it completes; find it in My places.",
            pending=True,
        )
    await state.kits.mark_order(order["id"], "failed", unless=("completed", "refunded"), **found)
    if facts["capture_status"] in ("DECLINED", "FAILED"):
        raise Problem(402, "PayPal declined the payment, so nothing was charged. Try again with another way to pay.", retry=False)
    log.error("Order %s was captured but not as sold: %s", order["id"], facts)
    raise HTTPException(502, f"PayPal's answer did not match this order, so no kit was made. Contact us with order {order['id']}.")


async def deliver(state, order: dict, capture_id: str | None, payer_id: str | None) -> dict:
    """The kit for a paid order (made now, building, or the one made before) and its build started."""
    run = await state.runs.fetch(order["survey_id"])
    concepts = run.concepts if run else []
    index = order["idx"]
    name = business_name(run, concepts[index], run.designs.get(index) or {}) if 0 <= index < len(concepts) else ""
    kit = await state.kits.deliver(
        order["id"], token=auth.new_token(), name=name or "Launch kit", capture_id=capture_id, payer_id=payer_id,
    )
    if kit["status"] == "building":
        state.builder.start(kit["token"])
    return kit


async def owners_kit(request: Request, token: str, user: dict) -> dict:
    kit = await request.app.state.kits.kit(token)
    if kit is None:
        raise HTTPException(404, "Kit not found.")
    if kit["user_id"] != user["id"]:
        raise HTTPException(403, "Only the kit's owner can do that.")
    return kit


@router.get("/kits/{token}")
async def kit_page(request: Request, token: str = Path(..., pattern=TOKEN)) -> dict:
    """A kit, for anyone with its link; the page asks again every 2 s while it builds."""
    state = request.app.state
    kit = await state.kits.kit(token)
    if kit is None:
        raise HTTPException(404, "Kit not found.")
    user = await auth.current_user(request)
    owner = user is not None and user["id"] == kit["user_id"]
    campaign = await state.campaigns.for_kit(token)
    until = kit["created_at"] + timedelta(days=settings.kit_refund_days)
    refundable = owner and kit["status"] != "refunded" and state.now() < until
    return {
        "token": kit["token"],
        "status": kit["status"],
        "survey_id": kit["survey_id"],
        "index": kit["idx"],
        "name": kit["name"] or "",
        "created_at": iso(kit["created_at"]),
        "survey_url": f"/s/{kit['survey_id']}?sheet={kit['idx']}",
        "is_owner": owner,
        "kit": kit["payload"] if kit["status"] == "ready" else None,
        "error": kit["error"] if kit["status"] == "failed" else None,
        "campaign_url": f"/p/{campaign['id']}" if campaign else None,
        "refundable_until": iso(until) if refundable else None,
    }


@router.post("/kits/{token}/retry", status_code=202)
async def retry(request: Request, user: auth.SignedIn, token: str = Path(..., pattern=TOKEN)) -> dict:
    """Builds a kit that failed again."""
    state = request.app.state
    await owners_kit(request, token, user)
    if not await state.kits.rebuild(token):
        raise HTTPException(409, "Only a kit that failed to build can be built again.")
    state.builder.start(token)
    return {"status": "building"}


@router.post("/kits/{token}/refund")
async def refund(request: Request, user: auth.SignedIn, token: str = Path(..., pattern=TOKEN)) -> dict:
    """Refunds the kit's payment through PayPal and revokes the kit, within KIT_REFUND_DAYS of buying it."""
    state = request.app.state
    kit = await owners_kit(request, token, user)
    if kit["status"] == "refunded":
        return {"status": "refunded"}
    days = settings.kit_refund_days
    if state.now() >= kit["created_at"] + timedelta(days=days):
        raise HTTPException(409, f"Kits can be refunded here for {days} days after buying. Contact us instead.")
    if await state.campaigns.for_kit(token, active=True):
        raise HTTPException(409, "This kit has a pledge campaign. Cancel the campaign before refunding the kit.")
    order = await state.kits.order(kit["order_id"])
    if not order or not order["capture_id"]:
        raise HTTPException(409, "This payment cannot be refunded here. Contact us instead.")
    client = paypal_client(request)
    try:
        await client.refund_capture(
            order["capture_id"], request_key("refund", order["capture_id"]), note="Your Walk-in launch kit was refunded.",
        )
    except PayPalError as exc:
        if not exc.has("CAPTURE_FULLY_REFUNDED"):
            raise paypal_problem(exc, "refund the payment") from exc
    await state.kits.refund(order["id"])
    return {"status": "refunded"}
