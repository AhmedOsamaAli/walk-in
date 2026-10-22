"""The survey's state: the site and the owner's brief, everything a run learns about it, and the runs in memory."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..catchment import Catchment
from .constraints import Constraints

Emit = Callable[[str, dict], Awaitable[None]]


@dataclass
class Site:
    lat: float
    lon: float
    label: str
    focus: str = "any"
    notes: str = ""
    minutes: int = 10
    # The unit, when the owner knows it: floor area, the kitchen it has (full, light or none) and outdoor space.
    size_m2: float | None = None
    kitchen: str | None = None
    outdoor: bool | None = None
    # What the owner wants: explore what fits, open a business of their choice, or improve their place on Qloo.
    intent: str = "explore"
    business: str = ""
    place_id: str = ""


@dataclass
class RunState:
    id: str
    site: Site
    # What the owner's notes rule in or out, read once (constraints.parse) so every step applies the same rules.
    constraints: Constraints = field(default_factory=Constraints)
    catchment: Catchment | None = None
    block: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    genres: list[dict] = field(default_factory=list)
    cues: list[str] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)
    explored: list[dict] = field(default_factory=list)  # genres the agent tested live, scored like the table
    fans: dict[str, dict] = field(default_factory=dict)  # genre id -> what local fans of that genre also love
    taste: dict = field(default_factory=dict)
    verdict: dict | None = None  # how the business the owner wants to open fits this site
    place: dict | None = None  # the owner's place, when improving it
    improve: dict | None = None
    concepts: list[dict] = field(default_factory=list)
    designs: dict[int, dict] = field(default_factory=dict)
    renders: dict[tuple[int, str], asyncio.Future] = field(default_factory=dict)  # (concept, shot) -> render
    queued: set[tuple[int, str]] = field(default_factory=set)  # shots whose render is still waiting in a free queue
    created_at: float = field(default_factory=time.time)


class RunStore:
    """The latest runs in memory; with a loader, older ones come back from the database when asked for."""

    def __init__(self, capacity: int = 100, load: Callable[[str], Awaitable[RunState | None]] | None = None) -> None:
        self._runs: OrderedDict[str, RunState] = OrderedDict()
        self._capacity = capacity
        self._load = load

    def add(self, run: RunState) -> None:
        self._runs[run.id] = run
        while len(self._runs) > self._capacity:
            self._runs.popitem(last=False)

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def forget(self, run_id: str) -> None:
        """Drops a run from memory, such as one whose survey was deleted with its owner's account."""
        self._runs.pop(run_id, None)

    async def fetch(self, run_id: str) -> RunState | None:
        """A run from memory, else loaded from the database and kept in memory again."""
        run = self._runs.get(run_id)
        if run is None and self._load is not None:
            loaded = await self._load(run_id)
            # Another request may have loaded the same run meanwhile; everyone keeps working on one copy.
            run = self._runs.get(run_id) or loaded
            if run is not None:
                self.add(run)
        return run


@dataclass
class EventLog:
    """What a survey has streamed: [event, data, seconds since it started] for each event, and how it is going."""

    run_id: str
    status: str = "running"  # running | complete | failed
    events: list[list] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started: float = field(default_factory=time.monotonic)

    def record(self, event: str, data: dict) -> None:
        self.events.append([event, data, round(time.monotonic() - self.started, 1)])


class LiveRuns:
    """Surveys running in this process. Each outlives the request that started it, so a refresh or a closed tab does
    not stop it, and leaves this list once it has been saved."""

    def __init__(self) -> None:
        self._logs: dict[str, EventLog] = {}
        self._tasks: set[asyncio.Task] = set()

    def get(self, run_id: str) -> EventLog | None:
        return self._logs.get(run_id)

    def start(self, log: EventLog, survey: Coroutine[Any, Any, None]) -> None:
        self._logs[log.run_id] = log
        task = asyncio.create_task(survey)
        self._tasks.add(task)

        def finished(done: asyncio.Task) -> None:
            self._tasks.discard(done)
            del self._logs[log.run_id]

        task.add_done_callback(finished)

    async def stop(self, grace: float) -> None:
        """Gives running surveys `grace` seconds to finish, then stops the rest, which are saved as failed."""
        if not self._tasks:
            return
        _, unfinished = await asyncio.wait(self._tasks, timeout=grace)
        for task in unfinished:
            task.cancel()
        await asyncio.gather(*unfinished, return_exceptions=True)
