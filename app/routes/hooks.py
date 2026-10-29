"""Calls that come from PayPal and from a scheduled job, never from a page: PayPal's webhook, verified with PayPal on the
raw body and handled once per event, and the settlement pass. Both settle what is due; neither is subject to the
Origin check, as each proves itself otherwise."""
from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from ..config import settings
from ..payments.paypal import PAYOUT_BATCH_EVENTS, PAYOUT_ITEM_EVENTS, RESOURCE_ID, PayPalError, net_amount
from ..payments.records import Problem, minor_or_none
from .campaigns import hold_pledge

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")
LARGEST_EVENT = 1_000_000
# A capture's refusal or reversal, as the pledge's status and its error.
CAPTURE_REFUSED = {
    "PAYMENT.CAPTURE.DENIED": ("failed", "DENIED"),
    "PAYMENT.CAPTURE.DECLINED": ("failed", "DECLINED"),
    "PAYMENT.CAPTURE.REFUNDED": ("refunded", "REFUNDED"),
    "PAYMENT.CAPTURE.REVERSED": ("refunded", "REVERSED"),
}


def related(resource: dict) -> dict:
    """The resource's related ids: order_id, authorization_id, capture_id."""
    data = resource.get("supplementary_data")
    ids = data.get("related_ids") if isinstance(data, dict) else None
    return {key: value for key, value in (ids or {}).items() if isinstance(value, str) and RESOURCE_ID.match(value)}


def link_to(resource: dict, kind: str) -> str | None:
    """The id at the end of the resource's 'up' link to a payment of this kind ('captures', 'authorizations')."""
    for link in resource.get("links") or []:
        href = str(link.get("href") or "") if isinstance(link, dict) else ""
        if link.get("rel") == "up" and f"/{kind}/" in href:
            found = href.rstrip("/").rsplit("/", 1)[-1]
            return found if RESOURCE_ID.match(found) else None
    return None


async def pledge_of_capture(state, resource: dict) -> dict | None:
    """The pledge a capture event is about: by the capture's id, else by the authorization it came from."""
    capture_id = resource.get("id")
    if isinstance(capture_id, str) and RESOURCE_ID.match(capture_id):
        found = await state.campaigns.pledge(capture_id=capture_id)
        if found:
            return found
    authorization_id = related(resource).get("authorization_id") or link_to(resource, "authorizations")
    return await state.campaigns.pledge_by_authorization(authorization_id) if authorization_id else None


async def order_approved(request: Request, resource: dict) -> None:
    """A supporter approved a pledge in PayPal but the campaign's page never held it (they closed the tab on the way
    back): the server holds it now, while the campaign takes pledges, else releases any hold PayPal placed."""
    state = request.app.state
    order_id = resource.get("id")
    found = await state.campaigns.pledge(order_id=order_id) if isinstance(order_id, str) else None
    if found is None or found["status"] != "created":
        return
    try:
        await hold_pledge(request, found)
    except (Problem, HTTPException) as exc:
        log.info("Approved pledge %s was not held from its webhook: %s", found["id"], getattr(exc, "detail", exc))


async def authorization_created(request: Request, resource: dict) -> None:
    """A hold PayPal placed that the app did not record (its answer was lost): the pledge is held as PayPal has it."""
    order_id = related(resource).get("order_id")
    if order_id:
        await order_approved(request, {"id": order_id})


async def authorization_voided(request: Request, resource: dict) -> None:
    """A pledge's hold was released outside the app: it no longer counts."""
    state = request.app.state
    authorization_id = resource.get("id")
    found = await state.campaigns.pledge_by_authorization(authorization_id) if isinstance(authorization_id, str) else None
    if found is not None:
        await state.campaigns.update_pledge(found["id"], only=("authorized",), status="voided")


async def capture_completed(request: Request, resource: dict, status: str) -> None:
    """A pledge collected (or under review at PayPal): its capture's status, and its net once PayPal itemizes it."""
    state = request.app.state
    found = await pledge_of_capture(state, resource)
    if found is None or found["status"] not in ("authorized", "captured"):
        return
    values: dict[str, object] = {"status": "captured", "capture_status": status, "error": None}
    if isinstance(resource.get("id"), str) and RESOURCE_ID.match(resource["id"]):
        values["capture_id"] = resource["id"]
    net = net_amount(resource)
    if net:
        values["net_cents"] = minor_or_none(net[0], net[1])
    if found["status"] == "authorized":
        values["captured_at"] = state.now()
    await state.campaigns.update_pledge(found["id"], only=("authorized", "captured"), **values)


async def capture_refused(request: Request, resource: dict, kind: str) -> None:
    """A collected pledge's payment was denied, declined, refunded or reversed: it no longer counts toward the payout."""
    state = request.app.state
    status, code = CAPTURE_REFUSED[kind]
    resource = dict(resource)
    if kind in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED") and not resource.get("seller_receivable_breakdown"):
        # A refund event carries the refund; the capture it returns is behind its 'up' link.
        behind = link_to(resource, "captures")
        if behind:
            resource["id"] = behind
    found = await pledge_of_capture(state, resource)
    if found is not None:
        await state.campaigns.update_pledge(
            found["id"], only=("captured", "authorized"), status=status, error=code, capture_status=code[:16],
        )


async def payout_changed(request: Request, kind: str, resource: dict) -> None:
    """A payout batch or item moved on at PayPal: the owner's payout says so. A batch's event carries only its header,
    and a batch PayPal processed may still hold an item it could not pay, so the batch is read back with its items."""
    state = request.app.state
    header = resource.get("batch_header") if isinstance(resource.get("batch_header"), dict) else {}
    item = resource.get("payout_item") if isinstance(resource.get("payout_item"), dict) else {}
    sender = header.get("sender_batch_header") if isinstance(header.get("sender_batch_header"), dict) else {}
    batch_id = header.get("payout_batch_id") or resource.get("payout_batch_id")
    payout = await state.campaigns.payout_by_batch(batch_id) if isinstance(batch_id, str) else None
    if payout is None:
        for campaign_id in (sender.get("sender_batch_id"), resource.get("sender_batch_id"), item.get("sender_item_id")):
            if isinstance(campaign_id, str) and campaign_id:
                payout = await state.campaigns.payout(campaign_id)
                if payout:
                    break
    if payout is None:
        return
    if kind in PAYOUT_BATCH_EVENTS and isinstance(batch_id, str) and RESOURCE_ID.match(batch_id):
        try:
            resource = await state.services.paypal.get_payout_batch(batch_id)
        except PayPalError as exc:
            log.info("Payout batch %s could not be read back: %s; the next pass asks again", batch_id, exc)
            return
    await state.settler.record_payout(payout["campaign_id"], resource)


async def handle(request: Request, kind: str, resource: dict) -> bool:
    """Acts on one event; False when the app does not listen to its kind."""
    if kind == "CHECKOUT.ORDER.APPROVED":
        await order_approved(request, resource)
    elif kind == "PAYMENT.AUTHORIZATION.CREATED":
        await authorization_created(request, resource)
    elif kind == "PAYMENT.AUTHORIZATION.VOIDED":
        await authorization_voided(request, resource)
    elif kind == "PAYMENT.CAPTURE.COMPLETED":
        await capture_completed(request, resource, "COMPLETED")
    elif kind == "PAYMENT.CAPTURE.PENDING":
        await capture_completed(request, resource, "PENDING")
    elif kind in CAPTURE_REFUSED:
        await capture_refused(request, resource, kind)
    elif kind in PAYOUT_BATCH_EVENTS or kind in PAYOUT_ITEM_EVENTS:
        await payout_changed(request, kind, resource)
    else:
        return False
    return True


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request, background: BackgroundTasks) -> dict:
    """An event from PayPal, handled once: verified with PayPal first (on the body exactly as sent), then kept by its
    id; then a settlement pass runs. Events of other kinds, and events seen before, are acknowledged and ignored."""
    state = request.app.state
    client = state.services.paypal
    if client is None or not client.configured or not settings.paypal_webhook_id:
        raise HTTPException(404, "Not Found")
    raw = await request.body()
    if len(raw) > LARGEST_EVENT:
        raise HTTPException(413, "The event is too large.")
    try:
        genuine = await client.verify_webhook_signature(request.headers, raw, settings.paypal_webhook_id)
    except PayPalError as exc:
        raise HTTPException(503, "PayPal could not confirm the event right now; it will be sent again.") from exc
    if not genuine:
        raise HTTPException(400, "The event could not be verified with PayPal.")
    event = json.loads(raw)
    event_id, kind = event.get("id"), event.get("event_type")
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    if not isinstance(event_id, str) or not event_id or not isinstance(kind, str):
        raise HTTPException(400, "That is not a PayPal event.")
    resource_id = resource.get("id") if isinstance(resource.get("id"), str) else None
    if not await state.events.record(event_id, kind, resource_id, event):
        return {"status": "duplicate"}
    try:
        handled = await handle(request, kind, resource)
    except Exception:
        await state.events.forget(event_id)  # so PayPal's next delivery is handled again
        raise
    background.add_task(state.settler.run_once)
    return {"status": "ok" if handled else "ignored"}


@router.post("/cron/settle")
async def cron_settle(request: Request, x_cron_secret: str | None = Header(None)) -> dict:
    """Runs one settlement pass (campaigns due, then payouts ready), for a scheduled job, so campaigns settle even when
    the server slept through their close."""
    secret = settings.cron_secret
    if not secret:
        raise HTTPException(404, "Not Found")
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret.encode("utf-8"), secret.encode("utf-8")):
        raise HTTPException(403, "Wrong cron secret.")
    return await request.app.state.settler.run_once()
