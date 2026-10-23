"""Launch kits, built in the background: the concept's design sheet first when it has none (as POST /api/design makes
it), then the kit itself (app.survey.kit.build_kit), whose payload includes the dossier.

A build outlives the request that started it. On shutdown the builds still running are cancelled and their kits stay
"building"; the next start builds them again (resume), so a restart never loses a kit.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .db import KitStore, SurveyStore
from .survey import design as designs
from .survey import kit as launch_kit
from .survey.models import RunState, RunStore

if TYPE_CHECKING:
    from .main import Services

log = logging.getLogger("walkin")

# Builds that run at once; the others wait their turn, so a burst of kits does not burst the free model quotas.
BUILDS_AT_ONCE = 3
FAILED = "Something went wrong while building the kit. Try again."
UNSAVED = "The survey this kit is for is no longer saved, so the kit cannot be built. Run the site again."


class KitUnavailable(RuntimeError):
    """A kit that cannot be built; the message says why, in plain words."""


async def designed(services: Services, surveys: SurveyStore, run: RunState, index: int) -> dict:
    """The concept's design sheet, designed and saved now when it has none. When two requests design the same concept,
    the first sheet stays, in memory as in the database."""
    sheet = run.designs.get(index)
    if sheet is not None:
        return sheet
    made = await designs.design_concept(services.llm, services.images, run, index, services.qloo, services.answers)
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
        """Cancels the builds still running; their kits stay "building" for the next start."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

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
        sheet = await designed(services, self._surveys, run, index)
        return await launch_kit.build_kit(services.llm, run, index, sheet, services.answers)
