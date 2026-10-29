"""Settling pledge campaigns, then paying their owners: once a campaign closes, collect every hold if it met its goal,
else release them all; once it is collected, PayPal Payouts sends the net collected total (after PayPal's fees) to the
owner's PayPal email.

A background loop settles every campaign that is due every few minutes (and at startup), keeps collecting funded ones
whose pledges could not all be collected yet, and pays out the ones that are done. A scheduled job (POST
/api/cron/settle) and PayPal's webhooks run the same pass, so a free instance that slept through a deadline still
settles soon after. The owner closing or cancelling a campaign settles it at once. All of them share one lock, so a
campaign is never settled twice at the same time; holding or withdrawing a pledge takes it too (app.routes.campaigns),
so no pledge changes while its campaign closes or settles. A pass with nothing due costs two queries.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from .db import tables
from .db.campaigns import CampaignStore
from .payments import pledges
from .payments.paypal import (
    PayPalClient,
    PayPalError,
    duplicate_payout,
    net_amount,
    request_key,
    summarize_payout,
)
from .payments.records import campaign_of, major, minor_or_none, pledge_of

log = logging.getLogger("walkin")

# What a settlement may change on a pledge, as the pledges module reports it.
PLEDGE_FIELDS = ("status", "capture_id", "capture_status", "error", "reauthorization_id", "reauthorized_at")
# PayPal's statuses and issue codes are short, but nothing in its answers bounds them: a pledge keeps what fits.
CODE_LENGTHS = {field: tables.pledges.c[field].type.length for field in ("capture_status", "error")}
# A capture's status at PayPal, as the pledge's: still collected, never collected, or given back.
CAPTURE_OUTCOME = {
    "COMPLETED": pledges.PledgeStatus.CAPTURED, "PENDING": pledges.PledgeStatus.CAPTURED,
    "PARTIALLY_REFUNDED": pledges.PledgeStatus.CAPTURED, "DECLINED": pledges.PledgeStatus.FAILED,
    "FAILED": pledges.PledgeStatus.FAILED, "REFUNDED": pledges.PledgeStatus.REFUNDED,
}
PAYOUT_SUBJECT = "Your founding supporters' pledges"


class Refused(Exception):
    """The owner cannot close or cancel the campaign as it stands now; the message says why, in plain words."""


class Settler:
    def __init__(self, campaigns: CampaignStore, paypal: PayPalClient | None, now: Callable[[], datetime]) -> None:
        self.campaigns = campaigns
        self.paypal = paypal
        self.now = now
        self.lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def run_once(self, now: datetime | None = None) -> dict:
        """Settles every campaign that is due and pays out every one that is ready, one at a time; what became of
        each: {"settled": [{"id", "status"}], "payouts": [{"id", "status"}]}."""
        if self.paypal is None:
            return {"settled": [], "payouts": []}
        async with self.lock:
            moment = now or self.now()
            settled, paid = [], []
            for campaign_id in await self.campaigns.due(moment):
                try:
                    result = await self._settle(campaign_id, moment)
                except Exception:
                    log.error("Settling campaign %s failed; the next pass tries again", campaign_id, exc_info=True)
                else:
                    if result:
                        settled.append(result)
            for campaign_id in await self.campaigns.payouts_due():
                try:
                    result = await self._pay_out(campaign_id)
                except Exception:
                    log.error("Paying out campaign %s failed; the next pass tries again", campaign_id, exc_info=True)
                else:
                    if result:
                        paid.append(result)
            return {"settled": settled, "payouts": paid}

    async def close(self, campaign_id: str, *, cancel: bool = False, now: datetime | None = None) -> None:
        """Closes an open campaign now and settles it: collected (then paid out) if it met its goal, released if not.
        Cancelling releases every hold. The owner's conditions are checked under the lock, on the campaign and its
        pledges as they stand then (a pledge held or withdrawn a moment before counts): closing early needs the goal
        met; cancelling needs it not met and the campaign not settled. Refused says why not."""
        async with self.lock:
            moment = now or self.now()
            row = await self.campaigns.get(campaign_id)
            if row is None:
                return
            campaign = campaign_of(row)
            if campaign.status == pledges.CampaignStatus.OPEN:
                found = [pledge_of(pledge, row["currency"]) for pledge in await self.campaigns.pledges([campaign_id])]
                funded = pledges.progress(campaign, found, moment)["funded"]
                if cancel and funded:
                    raise Refused("This campaign met its goal: close it to collect the pledges.")
                if not cancel and not funded and moment < pledges.closing_time(campaign):
                    raise Refused("Close early once the goal is met; to end the campaign short of it, cancel it.")
            elif cancel and campaign.status != pledges.CampaignStatus.CANCELLED:
                raise Refused("This campaign is settled, so it can no longer be cancelled.")
            values: dict[str, object] = {}
            if campaign.status == pledges.CampaignStatus.OPEN and moment < pledges.closing_time(campaign):
                values["closed_at"] = moment
            if cancel and campaign.status == pledges.CampaignStatus.OPEN and campaign.funded is None:
                values.update(status=pledges.CampaignStatus.CANCELLED.value, funded=False)
                values.setdefault("closed_at", moment)
            if values:
                await self.campaigns.update(campaign_id, **values)
            if self.paypal is None:
                return
            await self._settle(campaign_id, moment)
            if campaign_id in await self.campaigns.payouts_due():
                await self._pay_out(campaign_id)

    async def _settle(self, campaign_id: str, now: datetime) -> dict | None:
        """One settlement of one campaign, under the lock: the funded decision is stored before anything is collected,
        then the campaign's new status, its report and every pledge that changed. Captures PayPal had not completed or
        itemized are asked about first."""
        row = await self.campaigns.get(campaign_id)
        if row is None:
            return None
        campaign = campaign_of(row)
        stored = [pledge_of(pledge, row["currency"]) for pledge in await self.campaigns.pledges([campaign_id])]
        before = {pledge.id: pledge for pledge in stored}
        found = [await self._refreshed(pledge) for pledge in stored]

        async def record(decided: pledges.Campaign) -> None:
            await self.campaigns.update(campaign_id, funded=decided.funded, status=str(decided.status))

        result = await pledges.settle(campaign, found, self.paypal, now, record=record)
        changes = {}
        for pledge in result.pledges:
            earlier = before[pledge.id]
            values = {field: getattr(pledge, field) for field in PLEDGE_FIELDS if getattr(pledge, field) != getattr(earlier, field)}
            if pledge.net_amount != earlier.net_amount:
                values["net_cents"] = minor_or_none(pledge.net_amount, row["currency"])
            if values:
                values["status"] = str(pledge.status)
                for field, length in CODE_LENGTHS.items():
                    if isinstance(values.get(field), str):
                        values[field] = values[field][:length]
                if pledge.status == pledges.PledgeStatus.CAPTURED and earlier.status != pledges.PledgeStatus.CAPTURED:
                    values["captured_at"] = now
                changes[pledge.id] = values
        settled = result.campaign
        update: dict[str, object] = {"status": str(settled.status), "funded": settled.funded}
        if settled.status != pledges.CampaignStatus.OPEN:
            update["report"] = result.reasons
        if update["status"] == row["status"] and update["funded"] == row["funded"] and update.get("report", row["report"]) == row["report"]:
            update = {}
        if changes or update:
            await self.campaigns.save(campaign_id, update, changes)
        if result.outcomes or settled.status != row["status"]:
            log.info("Settled campaign %s: %s, %d pledges acted on", campaign_id, settled.status, len(result.outcomes))
        return {"id": campaign_id, "status": str(settled.status)}

    async def _refreshed(self, pledge: pledges.Pledge) -> pledges.Pledge:
        """A collected pledge as its capture stands at PayPal now, when PayPal had not completed or itemized it: its
        status, its net after PayPal's fee, or that it was declined or refunded since. Unchanged when PayPal does not
        answer."""
        if pledge.status != pledges.PledgeStatus.CAPTURED or not pledge.capture_id:
            return pledge
        if pledge.capture_status == "COMPLETED" and pledge.net_amount is not None:
            return pledge
        try:
            capture = await self.paypal.get_capture(pledge.capture_id)
        except (PayPalError, ValueError) as exc:
            log.info("Capture %s could not be read yet: %s", pledge.capture_id, exc)
            return pledge
        state = capture.get("status")
        net = net_amount(capture)
        changes: dict[str, object] = {}
        if isinstance(state, str) and state in CAPTURE_OUTCOME:
            changes["capture_status"] = state
            changes["status"] = CAPTURE_OUTCOME[state]
            if CAPTURE_OUTCOME[state] == pledges.PledgeStatus.FAILED:
                changes["error"] = state
        if net and net[1] == pledge.currency:
            changes["net_amount"] = net[0]
        return replace(pledge, **changes) if changes else pledge

    async def _pay_out(self, campaign_id: str) -> dict | None:
        """Pays the campaign's owner the net collected total once, or follows the payout PayPal already has.

        The payout is recorded as pending before PayPal is asked, with its amount and receiver, so a crash or an
        outage never pays twice: the request is sent again with the same PayPal-Request-Id and sender_batch_id (the
        campaign's id), which PayPal pays once."""
        row = await self.campaigns.get(campaign_id)
        if row is None:
            return None
        currency = row["currency"]
        collected = [
            pledge for pledge in await self.campaigns.pledges([campaign_id])
            if pledge["status"] == "captured" and pledge["capture_status"] == "COMPLETED" and pledge["net_cents"] is not None
        ]
        total = sum(pledge["net_cents"] for pledge in collected)
        if total <= 0:
            return None
        payout = await self.campaigns.start_payout(
            campaign_id, amount_cents=total, currency=currency, email=row["payout_email"],
        )
        if payout["status"] != "pending":
            return {"id": campaign_id, "status": payout["status"]}
        if payout["batch_id"]:
            try:
                answer = await self.paypal.get_payout_batch(payout["batch_id"])
            except PayPalError as exc:
                log.info("Payout %s could not be read yet: %s", payout["batch_id"], exc)
                return {"id": campaign_id, "status": "pending"}
            return {"id": campaign_id, "status": await self.record_payout(campaign_id, answer)}
        name = (row["offer"] or {}).get("name") or row["title"]
        supporters = len({pledge["payer_id"] or pledge["id"] for pledge in collected})
        amount = major(payout["amount_cents"], payout["currency"])
        try:
            answer = await self.paypal.create_payout(
                sender_batch_id=campaign_id, receiver=payout["email"], amount=amount, currency=payout["currency"],
                note=f"{supporters} founding supporters backed {name} with Walk-in Founders. This is their pledges, "
                     f"after PayPal's fees.",
                email_subject=PAYOUT_SUBJECT,
                email_message=f"Your campaign for {name} met its goal: here is what your founding supporters pledged.",
                request_id=request_key("payout", campaign_id),
            )
        except PayPalError as exc:
            original = duplicate_payout(exc)
            if original:
                await self.campaigns.update_payout(campaign_id, unless=("paid", "failed"), batch_id=original, error=None)
                return {"id": campaign_id, "status": "pending"}
            if exc.retryable or exc.status in (401, 403):
                await self.campaigns.update_payout(campaign_id, unless=("paid", "failed"), error=str(exc)[:200])
                log.warning("Payout of campaign %s did not reach PayPal; the next pass tries again: %s", campaign_id, exc)
                return {"id": campaign_id, "status": "pending"}
            await self.campaigns.update_payout(campaign_id, unless=("paid", "failed"), status="failed", error=str(exc)[:200])
            log.error("PayPal refused the payout of campaign %s: %s", campaign_id, exc)
            return {"id": campaign_id, "status": "failed"}
        log.info("Paid out campaign %s: %s %s", campaign_id, amount, payout["currency"])
        return {"id": campaign_id, "status": await self.record_payout(campaign_id, answer)}

    async def record_payout(self, campaign_id: str, answer: dict) -> str:
        """Stores what PayPal says of a campaign's payout (a batch, or one of its items); its status now. A payout paid
        or failed for good changes no more."""
        facts = summarize_payout(answer)
        values: dict[str, object] = {"status": facts["status"]}
        if facts["payout_batch_id"]:
            values["batch_id"] = facts["payout_batch_id"]
        if facts["payout_item_id"]:
            values["item_id"] = facts["payout_item_id"]
        state = facts["item_status"] or facts["batch_status"]
        if state:
            values["paypal_status"] = str(state)[:16]
        values["error"] = facts["error"] if facts["status"] == "failed" else None
        await self.campaigns.update_payout(campaign_id, unless=("paid", "failed"), **values)
        payout = await self.campaigns.payout(campaign_id)
        return payout["status"] if payout else facts["status"]

    # The background loop

    def start(self, every: float) -> None:
        self._task = asyncio.create_task(self._loop(every))

    async def _loop(self, every: float) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.error("Settlement pass failed", exc_info=True)
            await asyncio.sleep(every)

    async def stop(self, grace: float) -> None:
        """Lets a settlement in progress finish (up to `grace` seconds), then stops the loop."""
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(self.lock.acquire(), grace)
        except TimeoutError:
            held = False
        else:
            held = True
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if held:
            self.lock.release()
