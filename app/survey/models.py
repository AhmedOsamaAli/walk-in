"""The survey's state: the site and the owner's brief, and everything a run learns about it."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

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
    def __init__(self, capacity: int = 100) -> None:
        self._runs: OrderedDict[str, RunState] = OrderedDict()
        self._capacity = capacity

    def add(self, run: RunState) -> None:
        self._runs[run.id] = run
        while len(self._runs) > self._capacity:
            self._runs.popitem(last=False)

    def get(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)
