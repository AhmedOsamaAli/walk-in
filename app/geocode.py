"""Address search through OpenStreetMap Nominatim, throttled to its 1 request/second policy and cached."""
from __future__ import annotations

import asyncio
import time

import httpx


class Geocoder:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._cache: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._http = http_client or httpx.AsyncClient(
            base_url="https://nominatim.openstreetmap.org",
            headers={"User-Agent": "Walk-in/0.2 (Qloo Agentic Hackathon demo)"},
            timeout=15,
        )

    async def search(self, query: str) -> list[dict]:
        key = query.strip().lower()
        if key in self._cache:
            return self._cache[key]
        async with self._lock:
            wait = 1.0 - (time.time() - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            response = await self._http.get("/search", params={"q": query, "format": "jsonv2", "limit": 5})
            self._last = time.time()
        response.raise_for_status()
        results = [
            {"label": item.get("display_name"), "lat": float(item["lat"]), "lon": float(item["lon"])}
            for item in response.json()
        ]
        self._cache[key] = results
        return results

    async def aclose(self) -> None:
        await self._http.aclose()
