"""A run's state as JSON and back, so a finished survey outlives the process that ran it.

A restored run can be designed and rendered like the original. Renders in progress (asyncio futures) and the render
queue belong to the process and are left out; renders themselves are cached on disk (app.answers).
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from ..catchment import Catchment
from ..db import SurveyStore
from .constraints import Constraints
from .models import RunState, Site

LIVE_ONLY = {"renders", "queued"}


def dump_run(run: RunState) -> dict:
    """The run as JSON-safe data: dataclasses become objects, tuples and sets lists, design sheets keyed by text."""
    data = {f.name: plain(getattr(run, f.name)) for f in fields(run) if f.name not in LIVE_ONLY}
    data["designs"] = {str(index): plain(sheet) for index, sheet in run.designs.items()}
    return data


def load_run(data: dict) -> RunState:
    """The RunState a snapshot was taken from. Typed fields get their types back: the site, the owner's rules, the
    walk's (lon, lat) points and design sheets keyed by number. Tuples inside free-form data, such as the block
    summary's (genre, count) pairs, come back as the lists JSON keeps. Fields an older snapshot lacks keep defaults."""
    values = known(RunState, data)
    values["site"] = Site(**known(Site, data["site"]))
    constraints = known(Constraints, data.get("constraints") or {})
    if constraints.get("price"):
        constraints["price"] = tuple(constraints["price"])
    values["constraints"] = Constraints(**constraints)
    if data.get("catchment"):
        catchment = known(Catchment, data["catchment"])
        values["catchment"] = Catchment(**{**catchment, "ring": [tuple(point) for point in catchment["ring"]]})
    values["designs"] = {int(index): sheet for index, sheet in (data.get("designs") or {}).items()}
    return RunState(**values)


async def restore(surveys: SurveyStore, run_id: str) -> RunState | None:
    """A saved survey with every design sheet made for it; None when it is unknown or has no saved state (it is still
    running, or a restart cut it off)."""
    row = await surveys.get(run_id)
    if not row or not row["state"]:
        return None
    run = load_run(row["state"])
    run.designs.update(await surveys.get_designs(run_id))
    return run


def plain(value: Any) -> Any:
    """The value in JSON's types; anything JSON cannot hold is an error rather than a silent change."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [plain(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(plain(item) for item in value)
    if value is None or isinstance(value, str | int | float):
        return value
    raise TypeError(f"A run cannot be saved with a {type(value).__name__} in it")


def known(cls: type, data: dict) -> dict:
    """The entries of `data` that are fields of the dataclass `cls`, minus the live-only ones."""
    names = {f.name for f in fields(cls) if f.init} - LIVE_ONLY
    return {name: value for name, value in data.items() if name in names}
