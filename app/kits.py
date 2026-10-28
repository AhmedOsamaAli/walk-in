"""Launch kits, built in the background: the concept's design sheet first when it has none (as POST /api/design makes
it), then the kit itself (app.survey.kit.build_kit), whose payload includes the dossier, and the street map its poster
and report draw (app.basemap: OpenStreetMap's Overpass servers, else OpenFreeMap's vector tiles of the same data,
app.vectortiles), fetched meanwhile.

A kit saved without its street map, because neither source answered while it was built, gets it when it is opened
next (KitBuilder.with_streets): the tiles are asked first (they answer in seconds), the kit is saved with the map, and
the page waits for it at most FILL_WAIT_S seconds; a slower fetch goes on in the background, so the next open has it.
One fetch per kit at a time; after one fails, the kit is not asked for again for FILL_REST_S seconds.

A build outlives the request that started it. On shutdown the builds still running are cancelled and their kits stay
"building"; the next start builds them again (resume), so a restart never loses a kit.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from functools import partial
from typing import TYPE_CHECKING

from . import basemap, osm, vectortiles
from .config import settings
from .db import KitStore, SurveyStore
from .survey import design as designs
from .survey import kit as launch_kit
from .survey.models import RunState, RunStore

if TYPE_CHECKING:
    from .services import Services

log = logging.getLogger("walkin")

# Builds that run at once; the others wait their turn, so a burst of kits does not burst the free model quotas.
BUILDS_AT_ONCE = 3
FAILED = "Something went wrong while building the kit. Try again."
UNSAVED = "The survey this kit is for is no longer saved, so the kit cannot be built. Run the site again."
FILL_WAIT_S = 10.0  # how long opening a kit waits for its missing street map; the fetch goes on after that
FILL_REST_S = 600.0  # a kit whose missing street map could not be fetched is not asked for again for this long


def street_tiles(services: Services) -> vectortiles.TileClient | None:
    """The street map's second source: the app's own (a `tiles` service) when it has one, else OpenFreeMap's tiles, kept
    next to the Overpass cache, when the app asks Overpass itself. With a fake OpenStreetMap or none, as in tests,
    there is none, so nothing is downloaded."""
    given = getattr(services, "tiles", None)
    if given is not None:
        return given
    if isinstance(services.osm, osm.OsmClient):
        return vectortiles.TileClient(settings.cache_dir.parent / "tiles")
    return None


class KitUnavailable(RuntimeError):
    """A kit that cannot be built; the message says why, in plain words."""


async def designed(services: Services, surveys: SurveyStore, run: RunState, index: int) -> dict:
    """The concept's design sheet, designed and saved now when it has none. When two requests design the same concept,
    the first sheet stays, in memory as in the database."""
    sheet = run.designs.get(index)
    if sheet is not None:
        return sheet
    made = await designs.design_concept(run, index, services.qloo)
    sheet = run.designs.setdefault(index, made)
    try:
        await surveys.save_design(run.id, index, sheet)
    except Exception:
        log.warning("Could not save design sheet %d of survey %s", index, run.id, exc_info=True)
    return sheet


class KitBuilder:
    """Builds kits in the background, one build per kit at a time and BUILDS_AT_ONCE builds in all."""

    def __init__(self, store: KitStore, runs: RunStore, surveys: SurveyStore, services: Services) -> None:
        self._store, self._runs, self._surveys, self._services = store, runs, surveys, services
        self._tasks: dict[str, asyncio.Task] = {}
        self._gate = asyncio.Semaphore(BUILDS_AT_ONCE)
        # One street map at a time: a survey's kits ask for the same one, and the others then read it from the cache.
        self._maps = asyncio.Semaphore(1)
        self.tiles = street_tiles(services)
        self._own_tiles = self.tiles is not None and getattr(services, "tiles", None) is None
        # Street maps fetched for kits saved without one: one per kit at a time, one kit at a time, a rest after failing.
        self._fills: dict[str, asyncio.Task] = {}
        self._fill_gate = asyncio.Semaphore(1)
        self._failed_fills: dict[str, float] = {}

    def start(self, token: str) -> None:
        """Builds the kit in the background, unless it is being built already."""
        if token in self._tasks:
            return
        task = asyncio.create_task(self._build(token))
        self._tasks[token] = task

        def finished(done: asyncio.Task) -> None:
            if self._tasks.get(token) is done:
                del self._tasks[token]

        task.add_done_callback(finished)

    async def resume(self) -> int:
        """Builds again every kit a restart cut off; how many."""
        tokens = await self._store.building()
        for token in tokens:
            self.start(token)
        return len(tokens)

    async def stop(self) -> None:
        """Cancels the builds and street-map fetches still running; their kits stay "building", or without a street map,
        for the next start."""
        tasks = [*self._tasks.values(), *self._fills.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._own_tiles and self.tiles is not None:
            await self.tiles.aclose()

    async def _build(self, token: str) -> None:
        async with self._gate:
            try:
                kit = await self._store.kit(token, with_payload=False)
                if kit is None or kit["status"] != "building":
                    return
                try:
                    payload = await self._make(kit["survey_id"], kit["idx"])
                except KitUnavailable as exc:
                    await self._store.finish(token, error=str(exc))
                except Exception:
                    log.error("Kit %s failed to build", token, exc_info=True)
                    await self._store.finish(token, error=FAILED)
                else:
                    await self._store.finish(token, payload=payload, name=payload.get("concept", {}).get("name"))
            except Exception:  # the database failed: the kit stays building, and the next start builds it
                log.error("Kit %s could not be saved", token, exc_info=True)

    async def _make(self, survey_id: str, index: int) -> dict:
        run = await self._runs.fetch(survey_id)
        if run is None or not 0 <= index < len(run.concepts):
            raise KitUnavailable(UNSAVED)
        services = self._services
        # The street map is fetched while the copy is written; the kit keeps it, so it is fetched once.
        streets = asyncio.ensure_future(self._street_map(run))
        try:
            sheet = await designed(services, self._surveys, run, index)
            return await launch_kit.build_kit(services.llm, run, index, sheet, services.answers, streets)
        finally:
            streets.cancel()

    async def _street_map(self, run: RunState) -> dict | None:
        catchment = run.catchment
        async with self._maps:
            return await basemap.street_map(self._services.osm, catchment, basemap.layers_for(catchment), self.tiles)

    # ---------- Kits saved without a street map ----------

    def fillable(self, kit: dict) -> bool:
        """Whether a street map may still be added to this kit when it is opened: it is ready, its maps lack one, and
        a source of it is configured. A kit that is not fillable will not change again."""
        if kit.get("status") != "ready" or not launch_kit.lacks_street_map(kit.get("payload")):
            return False
        return self._services.osm is not None or self.tiles is not None

    async def with_streets(self, kit: dict) -> dict:
        """The kit as its page shows it (KitStore.kit, with its payload): a ready kit whose maps lack the street map gets
        it now, saved with the kit, when it comes within FILL_WAIT_S seconds; otherwise the kit as it is, and the fetch
        goes on for the next open. Never raises."""
        if not self.fillable(kit):
            return kit
        token = kit["token"]
        if time.monotonic() - self._failed_fills.get(token, -math.inf) < FILL_REST_S:
            return kit
        task = self._fills.get(token)
        if task is None:
            task = asyncio.create_task(self._fill(token, kit["survey_id"]))
            self._fills[token] = task
            task.add_done_callback(partial(self._filled, token))
        try:
            payload = await asyncio.wait_for(asyncio.shield(task), FILL_WAIT_S)
        except TimeoutError:
            return kit
        return {**kit, "payload": payload} if payload is not None else kit

    def _filled(self, token: str, done: asyncio.Task) -> None:
        if self._fills.get(token) is done:
            del self._fills[token]

    async def _fill(self, token: str, survey_id: str) -> dict | None:
        """Fetches a ready kit's missing street map, the tiles first, and saves the kit with it in every map that lacks
        it; the payload saved, or None when no source answered (the kit then rests FILL_REST_S seconds)."""
        try:
            async with self._fill_gate:
                run = await self._runs.fetch(survey_id)
                catchment = run.catchment if run is not None else None
                streets = await basemap.street_map(self._services.osm, catchment, basemap.layers_for(catchment),
                                                   self.tiles, tiles_first=True)
            if streets is None:
                raise LookupError("no source of the street map answered")
            kit = await self._store.kit(token)
            if kit is None or kit["status"] != "ready" or not isinstance(kit.get("payload"), dict):
                return None
            payload = launch_kit.with_street_map(kit["payload"], streets)
            if not await self._store.save_payload(token, payload):
                return None
            log.info("Kit %s now has its street map (%s)", token[:8], streets.get("source"))
            return payload
        except Exception as exc:
            now = time.monotonic()
            self._failed_fills = {key: at for key, at in self._failed_fills.items() if now - at < FILL_REST_S}
            self._failed_fills[token] = now
            log.warning("No street map for kit %s yet (%s); asking again in %d minutes", token[:8], exc,
                        FILL_REST_S // 60, exc_info=not isinstance(exc, LookupError))
            return None
