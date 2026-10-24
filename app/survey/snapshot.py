"""A run's state as JSON and back, so a finished survey outlives the process that ran it.

A restored run can be designed and given a launch kit like the original.
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from ..catchment import Catchment
from ..db import SurveyStore
from .constraints import Constraints
from .models import RunState, Site


def dump_run(run: RunState) -> dict:
    """The run as JSON-safe data: dataclasses become objects, tuples and sets lists, design sheets keyed by text."""
    data = {f.name: plain(getattr(run, f.name)) for f in fields(run)}
    data["designs"] = {str(index): plain(sheet) for index, sheet in run.designs.items()}
    return data


def load_run(data: dict) -> RunState:
    """The RunState a snapshot was taken from. Typed fields get their types back: the site, the owner's rules, the
    walk's (lon, lat) points and design sheets keyed by number. Tuples inside free-form data, such as the block
    summary's (genre, count) pairs, come back as the lists JSON keeps. Fields an older snapshot lacks keep defaults."""
    values = known(RunState, data)
    values["site"] = Site(**known(Site, data["site"]))
    constraints = known(Constraints, data.get("constraints") or {})
    if isinstance(constraints.get("price"), list | tuple):
        # Older snapshots kept the band as the Qloo price levels it allowed: [1, 1], [2, 2] or [3, 4].
        constraints["price"] = {1: "budget", 2: "mid-range"}.get(constraints["price"][0], "upscale")
    values["constraints"] = Constraints(**constraints)
    if data.get("catchment"):
        catchment = known(Catchment, data["catchment"])
        around = catchment.get("around")
        values["catchment"] = Catchment(**{
            **catchment, "ring": [tuple(point) for point in catchment["ring"]],
            "around": [tuple(point) for point in around] if around else None,
        })
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
    """The entries of `data` that are fields of the dataclass `cls`; anything an older version saved is left out."""
    names = {f.name for f in fields(cls) if f.init}
    return {name: value for name, value in data.items() if name in names}
