"""Async Qloo API client with an on-disk response cache.

Qloo's hackathon terms allow private server-side caching; the cache directory is gitignored
so responses never end up in the public repository.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx


class QlooError(RuntimeError):
    pass


class QlooClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        cache_dir: Path,
        max_concurrency: int = 6,
        timeout: float = 45.0,
    ) -> None:
        # A missing key only fails live calls; cached responses keep working (useful after the hackathon key expires).
        self.configured = bool(api_key)
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
        )
        self._cache_dir = cache_dir
        self._gate = asyncio.Semaphore(max_concurrency)
        self._inflight: dict[str, asyncio.Future] = {}
        self.calls = 0
        self.cache_hits = 0

    async def aclose(self) -> None:
        await self._http.aclose()

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        normalized = json.dumps([path, sorted((k, str(v)) for k, v in params.items())])
        return hashlib.sha1(normalized.encode("utf-8")).hexdigest()

    async def get(self, path: str, params: dict[str, Any]) -> dict:
        key = self._cache_key(path, params)
        cache_file = self._cache_dir / f"{key}.json"
        if cache_file.exists():
            self.cache_hits += 1
            return json.loads(cache_file.read_text(encoding="utf-8"))
        if key in self._inflight:
            return await self._inflight[key]

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            data = await self._fetch(path, params)
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            future.set_result(data)
            return data
        except Exception as exc:
            future.set_exception(exc)
            future.exception()  # mark as retrieved so asyncio does not warn when nobody else awaits it
            raise
        finally:
            self._inflight.pop(key, None)

    async def _fetch(self, path: str, params: dict[str, Any]) -> dict:
        if not self.configured:
            raise QlooError("QLOO_API_KEY is not set, and this request is not cached.")
        async with self._gate:
            for attempt in range(4):
                try:
                    response = await self._http.get(path, params=params)
                except httpx.HTTPError as exc:
                    if attempt == 3:
                        raise QlooError(f"Network error calling Qloo {path}: {exc}") from exc
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt == 3:
                        raise QlooError(f"Qloo {path} returned HTTP {response.status_code}")
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    raise QlooError(f"Qloo {path} returned HTTP {response.status_code}: {response.text[:200]}")
                self.calls += 1
                return response.json()
        raise QlooError(f"Qloo {path}: retries exhausted")

    async def insights(self, params: dict[str, Any]) -> dict:
        return await self.get("/v2/insights", params)

    async def search(self, params: dict[str, Any]) -> dict:
        return await self.get("/search", params)

    async def tags(self, params: dict[str, Any]) -> dict:
        return await self.get("/v2/tags", params)
