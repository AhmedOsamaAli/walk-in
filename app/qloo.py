"""Async Qloo API client with an on-disk response cache.

Qloo's hackathon terms allow private server-side caching; the cache directory is gitignored
so responses never end up in the public repository. A cached answer is used for a week; after that Qloo is asked
again, and the older answer serves only when Qloo cannot answer (it is unreachable, or the key has expired).
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("walkin")

MAX_AGE_S = 7 * 24 * 3600


class QlooError(RuntimeError):
    pass


@dataclass
class Reads:
    """The Qloo answers one survey read: how many, and when the oldest of them came from Qloo."""

    queries: int = 0
    oldest: float | None = None  # seconds since the epoch

    def add(self, fetched_at: float) -> None:
        self.queries += 1
        if self.oldest is None or fetched_at < self.oldest:
            self.oldest = fetched_at


_reads: contextvars.ContextVar[Reads | None] = contextvars.ContextVar("qloo_reads", default=None)


def track_reads() -> Reads:
    """Counts the Qloo answers read from here on by the current task and the tasks it starts, so surveys running at the
    same time are counted apart."""
    reads = Reads()
    _reads.set(reads)
    return reads


def _count(fetched_at: float) -> None:
    reads = _reads.get()
    if reads is not None:
        reads.add(fetched_at)


def _saved(cache_file: Path) -> tuple[dict, float] | None:
    """A cached answer and when it was fetched."""
    try:
        return json.loads(cache_file.read_text(encoding="utf-8")), cache_file.stat().st_mtime
    except (OSError, ValueError):
        return None


class QlooClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        cache_dir: Path,
        max_concurrency: int = 6,
        timeout: float = 45.0,
        max_age_s: float = MAX_AGE_S,
    ) -> None:
        # A missing key only fails live calls; cached responses keep working (useful after the hackathon key expires).
        self.configured = bool(api_key)
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
        )
        self._cache_dir = cache_dir
        self._max_age_s = max_age_s
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
        saved = _saved(cache_file)
        if saved and time.time() - saved[1] < self._max_age_s:
            self.cache_hits += 1
            _count(saved[1])
            return saved[0]
        if key in self._inflight:
            data, fetched_at = await self._inflight[key]
            _count(fetched_at)
            return data

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            try:
                data, fetched_at = await self._fetch(path, params), time.time()
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            except QlooError as exc:
                if not saved:
                    raise
                log.warning("Qloo did not answer (%s); using its answer from %s", exc, time.ctime(saved[1]))
                data, fetched_at = saved
                self.cache_hits += 1
            future.set_result((data, fetched_at))
            _count(fetched_at)
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

    async def entities(self, params: dict[str, Any]) -> dict:
        return await self.get("/entities", params)

    async def tags(self, params: dict[str, Any]) -> dict:
        return await self.get("/v2/tags", params)
