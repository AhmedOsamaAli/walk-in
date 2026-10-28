"""Address search and the address at a point, through OpenStreetMap Nominatim, throttled to its 1 request/second
policy and cached."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

import httpx

from . import tls

# Nominatim's address parts: the street a storefront is on, then the parts of town from the smallest up; a label names
# the street address and the two smallest ('Williamsburg, Brooklyn', 'East Cesar Chavez, Austin').
STREET_KEYS = ("road", "pedestrian", "square", "footway", "path", "place")
TOWN_KEYS = ("neighbourhood", "quarter", "suburb", "hamlet", "village", "town", "city")
LABEL_MAX = 160  # a survey's site label is at most this long
PLACES_KEPT = 500


def address_of(data: dict) -> dict | None:
    """A reverse lookup's answer as {label, address}: the label is the street address and the two smallest parts of
    town ('131 South 2nd Street, Williamsburg, Brooklyn'), the address Nominatim's full line. None when the point has
    no address."""
    full = str(data.get("display_name") or "").strip()
    if data.get("error") or not full:
        return None
    parts = data.get("address") or {}
    street = next((str(parts[key]).strip() for key in STREET_KEYS if parts.get(key)), "")
    if not street:
        return {"label": ", ".join(full.split(", ")[:2])[:LABEL_MAX], "address": full}
    if parts.get("house_number"):
        street = f"{str(parts['house_number']).strip()} {street}"
    towns = list(dict.fromkeys(str(parts[key]).strip() for key in TOWN_KEYS if parts.get(key)))
    return {"label": ", ".join([street, *towns[:2]])[:LABEL_MAX], "address": full}


class Abandoned(Exception):
    """The lookup was called off before its turn: whoever asked has gone (the pin moved), so Nominatim is not asked."""


class Geocoder:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._cache: dict[str, list[dict]] = {}
        self._places: OrderedDict[str, dict | None] = OrderedDict()
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._http = http_client or httpx.AsyncClient(
            base_url="https://nominatim.openstreetmap.org",
            headers={"User-Agent": "Walk-in/0.2 (Qloo Agentic Hackathon demo)"},
            timeout=15,
            verify=tls.context(),
        )

    async def _get(
        self, path: str, params: dict, headers: dict | None = None,
        wanted: Callable[[], Awaitable[bool]] | None = None,
    ) -> httpx.Response:
        """One Nominatim request, a second after the last; `wanted` is asked once it is this one's turn, and a lookup
        nobody waits for any more raises Abandoned instead of using the turn."""
        async with self._lock:
            wait = 1.0 - (time.time() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            if wanted is not None and not await wanted():
                raise Abandoned
            try:
                return await self._http.get(path, params=params, headers=headers)
            finally:
                self._last = time.time()

    async def search(self, query: str) -> list[dict]:
        key = query.strip().lower()
        if key in self._cache:
            return self._cache[key]
        response = await self._get("/search", {"q": query, "format": "jsonv2", "limit": 5})
        response.raise_for_status()
        results = [
            {"label": item.get("display_name"), "lat": float(item["lat"]), "lon": float(item["lon"])}
            for item in response.json()
        ]
        self._cache[key] = results
        return results

    async def reverse(
        self, lat: float, lon: float, wanted: Callable[[], Awaitable[bool]] | None = None,
    ) -> dict | None:
        """The address at a point, as address_of gives it, in English where OpenStreetMap has it; None when the point
        has no address (open water, a field). Raises Abandoned when `wanted` says nobody waits for it any more."""
        key = f"{lat:.5f},{lon:.5f}"
        if key in self._places:
            return self._places[key]
        response = await self._get(
            "/reverse",
            {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2", "zoom": 18, "addressdetails": 1},
            headers={"Accept-Language": "en"},
            wanted=wanted,
        )
        response.raise_for_status()
        found = address_of(response.json())
        self._places[key] = found
        while len(self._places) > PLACES_KEPT:
            self._places.popitem(last=False)
        return found

    async def aclose(self) -> None:
        await self._http.aclose()
