"""Finished surveys and ready kits in memory, as the exact bytes their routes send.

Opening one then costs no database query (Neon sleeps after five idle minutes and its first query takes seconds) and no
JSON work (a survey's record runs to 120-200 KB). A page is kept only once it is final, so it never goes stale: a
survey's record once it has finished, a kit's page once it is ready with its street map; deleting a survey (with its
owner's account) drops both. The examples' pages are pinned, loaded as the server starts (app.routes.examples.warm_up);
the rest are kept while their bodies fit a memory budget sized for a 512 MB server (RESPONSE_CACHE_MB), the least
recently opened leaving first. A page is read once at a time: a visitor and the warm-up asking for the same one share
one read. A page is also kept gzipped (four times smaller, so a quarter more memory), made once, for the clients that
accept it: the front door's trip from Render crosses an ocean.
"""
from __future__ import annotations

import asyncio
import gzip
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cached_property, partial

from fastapi import Request, Response

from .config import settings

# Bytes of bodies kept besides the pinned examples: about 200 surveys or kits; their gzipped copies add about a quarter.
DEFAULT_BUDGET = 32 * 1024 * 1024
GZIP_LEVEL = 6  # the real examples come out 4x smaller; level 9 takes three times as long for 1 % more
GZIP_MIN_BYTES = 1024  # smaller bodies gain nothing worth the work


@dataclass(frozen=True)
class Page:
    """A response body as sent, the survey it shows, its status then, whether it is final (it will never change, so it
    is kept) and whether it is settled: nothing may still change what it shows (a survey still running here is saved
    first; a kit may still get its street map), so the front door may keep it once its status allows."""

    body: bytes
    survey_id: str
    status: str
    final: bool = True
    settled: bool = True

    @property
    def size(self) -> int:
        return len(self.body)

    @cached_property
    def gzipped(self) -> bytes:
        """The body gzipped, made the first time a client that accepts it asks."""
        return gzip.compress(self.body, compresslevel=GZIP_LEVEL, mtime=0)


def json_response(body: bytes, cache_control: str) -> Response:
    """A JSON body sent as it is: the headers FastAPI gives its own JSON responses, and the cache policy."""
    return Response(body, media_type="application/json", headers={"Cache-Control": cache_control})


def page_response(page: Page, cache_control: str, request: Request) -> Response:
    """A page as JSON: gzipped for a client that accepts it (app.main's GZipMiddleware leaves it as it is), else as it
    is; either way the same JSON."""
    if page.size < GZIP_MIN_BYTES:
        return json_response(page.body, cache_control)
    headers = {"Cache-Control": cache_control, "Vary": "Accept-Encoding"}
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(page.gzipped, media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(page.body, media_type="application/json", headers=headers)


class ResponseCache:
    """Pages by key ('run:<id>', 'kit:<token>'): the examples' stay; the others leave least recently used first once
    their bodies pass `budget` bytes."""

    def __init__(self, budget: int = DEFAULT_BUDGET) -> None:
        self.budget = budget
        self._pinned: dict[str, Page] = {}
        self._recent: OrderedDict[str, Page] = OrderedDict()
        self._reading: dict[str, asyncio.Future] = {}
        self._size = 0
        self._deletions = 0  # surveys forgotten so far: a page whose read saw one is not kept (it may show it)
        self.hits = 0
        self.misses = 0

    async def fetch(self, key: str, read: Callable[[], Awaitable[Page | None]]) -> Page | None:
        """The page under `key`: from memory, else read (None when there is none) and kept when it is final, unless a
        survey was deleted meanwhile. One read per key at a time: whoever asks meanwhile gets the same page."""
        found = self.get(key)
        if found is not None:
            return found
        reading = self._reading.get(key)
        if reading is None:
            reading = self._reading[key] = asyncio.ensure_future(read())
            reading.add_done_callback(partial(self._read, key, self._deletions))
        return await asyncio.shield(reading)

    def get(self, key: str) -> Page | None:
        """The page under `key` when it is in memory (it becomes the most recently opened), else None."""
        found = self._pinned.get(key)
        if found is None:
            found = self._recent.get(key)
            if found is not None:
                self._recent.move_to_end(key)
        if found is None:
            self.misses += 1
        else:
            self.hits += 1
        return found

    def put(self, key: str, page: Page) -> None:
        """Keeps a final page: pinned when it shows an example, else while it fits the budget."""
        self._drop(key)
        if page.survey_id in settings.examples:
            self._pinned[key] = page
            return
        if page.size > self.budget:
            return
        self._recent[key] = page
        self._size += page.size
        while self._size > self.budget:
            _, oldest = self._recent.popitem(last=False)
            self._size -= oldest.size

    def forget_survey(self, survey_id: str) -> None:
        """Drops everything that shows this survey: its record and its kits, and whatever a read in flight brings back
        (its page may show the survey; it reaches whoever asked, and is not kept)."""
        self._deletions += 1
        for key in [key for key, page in (*self._pinned.items(), *self._recent.items()) if page.survey_id == survey_id]:
            self._drop(key)

    def stats(self) -> dict:
        """What memory holds (pages and bytes of bodies) and how often it answered, for the log."""
        pinned = sum(page.size for page in self._pinned.values())
        return {"pinned": len(self._pinned), "recent": len(self._recent), "bytes": pinned + self._size,
                "hits": self.hits, "misses": self.misses}

    def _read(self, key: str, deletions: int, reading: asyncio.Future) -> None:
        """When a read ends: its page is kept if it is final and no survey was deleted while it was read."""
        if self._reading.get(key) is reading:
            del self._reading[key]
        if reading.cancelled() or reading.exception() is not None:  # retrieved: whoever waited has it
            return
        page = reading.result()
        if page is not None and page.final and deletions == self._deletions:
            self.put(key, page)

    def _drop(self, key: str) -> None:
        self._pinned.pop(key, None)
        old = self._recent.pop(key, None)
        if old is not None:
            self._size -= old.size
