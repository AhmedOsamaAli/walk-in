"""Calls that come from PayPal and from a scheduled job, never from a page: PayPal's webhook, and the settlement pass."""
from __future__ import annotations

import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from ..commerce import Problem
from ..config import settings
from ..payments.paypal import RESOURCE_ID, PayPalError
from .kits import settle_order

log = logging.getLogger("walkin")
router = APIRouter(prefix="/api")
LARGEST_EVENT = 1_000_000


def related(resource: dict) -> dict:
    """The resource's related ids: order_id, authorization_id, capture_id."""
    data = resource.get("supplementary_data")
    ids = data.get("related_ids") if isinstance(data, dict) else None
    return {key: value for key, value in (ids or {}).items() if isinstance(value, str) and RESOURCE_ID.match(value)}


def capture_behind(resource: dict) -> str | None:
    """The capture a refund or a reversal belongs to: its 'up' link, else its related ids."""
    for link in resource.get("links") or []:
        if not isinstance(link, dict):
            continue
        href = str(link.get("href") or "")
        if link.get("rel") == "up" and "/captures/" in href:
            return href.rstrip("/").rsplit("/", 1)[-1]
    return related(resource).get("capture_id")


async def capture_completed(request: Request, resource: dict) -> None:
    """A kit payment PayPal reviewed has completed: the kit is built now. A pledge collected is marked collected."""
    state = request.app.state
    ids = related(resource)
    order = await state.kits.order(ids["order_id"]) if "order_id" in ids else None
    if order is not None:
        if order["status"] in ("created", "pending") and await state.kits.kit_for_order(order["id"]) is None:
            paid = await state.services.paypal.get_order(order["id"])  # PayPal's word on the whole order
            try:
                await settle_order(state, order, paid)
            except (Problem, HTTPException) as exc:
                log.warning("Order %s was not delivered from its webhook: %s", order["id"], exc)
        return
    pledge = await state.campaigns.pledge_by_authorization(ids["authorization_id"]) if "authorization_id" in ids else None
    if pledge is not None:
        await state.campaigns.update_pledge(
            pledge["id"], only=("authorized",), status="captured", capture_id=resource.get("id"), captured_at=state.now(),
            error=None,
        )


async def capture_refused(request: Request, resource: dict, code: str) -> None:
    """A payment PayPal reviewed was denied: a kit order fails; a pledge collected that way could not be collected."""
    state = request.app.state
    ids = related(resource)
    order = await state.kits.order(ids["order_id"]) if "order_id" in ids else None
    if order is not None:
        await state.kits.mark_order(order["id"], "failed", unless=("completed", "refunded"))
        return
    capture_id = resource.get("id")
    pledge = await state.campaigns.pledge(capture_id=capture_id) if isinstance(capture_id, str) else None
    if pledge is not None:
        await state.campaigns.update_pledge(pledge["id"], only=("captured",), status="failed", error=code)


async def refunded(request: Request, resource: dict) -> None:
    """A kit's payment was refunded or reversed (from PayPal's side too): the kit is revoked."""
    state = request.app.state
    capture_id = capture_behind(resource)
    order = await state.kits.order_by_capture(capture_id) if capture_id else None
    if order is not None and order["status"] != "refunded":
        await state.kits.refund(order["id"])


async def authorization_voided(request: Request, resource: dict) -> None:
    """A pledge's hold was released outside the app: it no longer counts."""
    state = request.app.state
    authorization_id = resource.get("id")
    pledge = await state.campaigns.pledge_by_authorization(authorization_id) if isinstance(authorization_id, str) else None
    if pledge is not None:
        await state.campaigns.update_pledge(pledge["id"], only=("authorized",), status="voided")


async def handle(request: Request, kind: str, resource: dict) -> None:
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        await capture_completed(request, resource)
    elif kind in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
        await capture_refused(request, resource, kind.rsplit(".", 1)[-1])
    elif kind in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        await refunded(request, resource)
    elif kind == "PAYMENT.AUTHORIZATION.VOIDED":
        await authorization_voided(request, resource)


@router.post("/paypal/webhook")
async def paypal_webhook(request: Request) -> dict:
    """An event from PayPal, handled once: verified with PayPal first, then kept by its id."""
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
        await handle(request, kind, resource)
    except Exception:
        await state.events.forget(event_id)  # so PayPal's next delivery is handled again
        raise
    return {"status": "ok"}


@router.post("/cron/settle")
async def cron_settle(request: Request, x_cron_secret: str | None = Header(None)) -> dict:
    """Runs one settlement pass, for a scheduled job, so campaigns settle even when the server slept through their
    close."""
    secret = settings.cron_secret
    if not secret:
        raise HTTPException(404, "Not Found")
    if not x_cron_secret or not hmac.compare_digest(x_cron_secret.encode("utf-8"), secret.encode("utf-8")):
        raise HTTPException(403, "Wrong cron secret.")
    return {"settled": await request.app.state.settler.run_once()}
