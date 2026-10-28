"""Keeps a free Render instance awake. Render puts a free web service to sleep after 15 minutes without a visit, and the
first visit after that waits about 40 seconds while it wakes, so the app visits a health check every few minutes:
KEEP_AWAKE_URL, the front door's, so each visit leaves Render and comes back in from outside like a visitor's. The health
check reads no database, so Neon still scales to zero between surveys."""
from __future__ import annotations

import asyncio
import logging

import httpx

from . import tls

log = logging.getLogger("walkin")

# Seconds between visits: every 5 minutes leaves room for a failed visit inside Render's 15.
EVERY_S = 300.0


async def keep_awake(url: str, every: float = EVERY_S, transport: httpx.AsyncBaseTransport | None = None) -> None:
    """Visits `url` every `every` seconds until cancelled. A failed visit is logged, and the next one comes on time."""
    async with httpx.AsyncClient(
        timeout=30, headers={"User-Agent": "Walk-in keep-awake"}, transport=transport, verify=tls.context(),
    ) as client:
        while True:
            await asyncio.sleep(every)
            try:
                response = await client.get(url)
            except httpx.HTTPError as error:
                log.warning("Keep-awake: visiting %s failed (%s)", url, error)
                continue
            if response.status_code != 200:
                log.warning("Keep-awake: %s answered %s", url, response.status_code)
