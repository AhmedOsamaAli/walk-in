"""Settling pledge campaigns: once a campaign closes, collect every hold if it met its goal, else release them all.

A background loop settles every campaign that is due each minute (and at startup), and keeps collecting funded ones
whose pledges could not all be collected yet. A scheduled job (POST /api/cron/settle) runs the same pass, so a free
instance that slept through a deadline still settles soon after. The owner closing or cancelling a campaign settles it
at once. All of them share one lock, so a campaign is never settled twice at the same time.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from .commerce import campaign_of, pledge_of
from .db.campaigns import CampaignStore
from .payments import pledges
from .payments.paypal import PayPalClient

log = logging.getLogger("walkin")

# What a settlement may change on a pledge, as the pledges module reports it.
PLEDGE_FIELDS = ("status", "capture_id", "error", "reauthorization_id", "reauthorized_at")


class Settler:
    def __init__(self, campaigns: CampaignStore, paypal: PayPalClient | None, now: Callable[[], datetime]) -> None:
        self.campaigns = campaigns
        self.paypal = paypal
        self.now = now
        self.lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def run_once(self, now: datetime | None = None) -> list[dict]:
        """Settles every campaign that is due, one at a time; what became of each."""
        if self.paypal is None:
            return []
        async with self.lock:
            moment = now or self.now()
            results = []
            for campaign_id in await self.campaigns.due(moment):
                try:
                    results.append(await self._settle(campaign_id, moment))
                except Exception:
                    log.error("Settling campaign %s failed; the next pass tries again", campaign_id, exc_info=True)
            return [result for result in results if result]

    async def close(self, campaign_id: str, *, cancel: bool = False, now: datetime | None = None) -> None:
        """Closes an open campaign now and settles it: collected if it met its goal, released if not. Cancelling
        releases every hold whatever the count."""
        async with self.lock:
            moment = now or self.now()
            row = await self.campaigns.get(campaign_id)
            if row is None:
                return
            campaign = campaign_of(row)
            values: dict[str, object] = {}
            if campaign.status == pledges.CampaignStatus.OPEN and moment < pledges.closing_time(campaign):
                values["closed_at"] = moment
            if cancel and campaign.status == pledges.CampaignStatus.OPEN and campaign.funded is None:
                values.update(status=pledges.CampaignStatus.CANCELLED.value, funded=False)
                values.setdefault("closed_at", moment)
            if values:
                await self.campaigns.update(campaign_id, **values)
            if self.paypal is not None:
                await self._settle(campaign_id, moment)

    async def _settle(self, campaign_id: str, now: datetime) -> dict | None:
        """One settlement of one campaign, under the lock: the funded decision is stored before anything is collected,
        then the campaign's new status, its report and every pledge that changed."""
        row = await self.campaigns.get(campaign_id)
        if row is None:
            return None
        campaign = campaign_of(row)
        found = [pledge_of(pledge, row["currency"]) for pledge in await self.campaigns.pledges([campaign_id])]
        before = {pledge.id: pledge for pledge in found}

        async def record(decided: pledges.Campaign) -> None:
            await self.campaigns.update(campaign_id, funded=decided.funded, status=str(decided.status))

        result = await pledges.settle(campaign, found, self.paypal, now, record=record)
        changes = {}
        for pledge in result.pledges:
            earlier = before[pledge.id]
            values = {field: getattr(pledge, field) for field in PLEDGE_FIELDS if getattr(pledge, field) != getattr(earlier, field)}
            if values:
                values["status"] = str(pledge.status)
                if pledge.status == pledges.PledgeStatus.CAPTURED and earlier.status != pledges.PledgeStatus.CAPTURED:
                    values["captured_at"] = now
                changes[pledge.id] = values
        settled = result.campaign
        update: dict[str, object] = {"status": str(settled.status), "funded": settled.funded}
        if settled.status != pledges.CampaignStatus.OPEN:
            update["report"] = result.reasons
        if changes or update["status"] != row["status"] or update["funded"] != row["funded"] or update.get("report", row["report"]) != row["report"]:
            await self.campaigns.save(campaign_id, update, changes)
        if result.outcomes or settled.status != row["status"]:
            log.info("Settled campaign %s: %s, %d pledges acted on", campaign_id, settled.status, len(result.outcomes))
        return {"id": campaign_id, "status": str(settled.status)}

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
