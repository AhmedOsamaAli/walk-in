"""Surveys and their design sheets in the database.

A finished survey's state runs to megabytes of JSON, so it is stored compressed: zlib (level 6) of compact JSON, packed
and unpacked in a worker thread so the event loop keeps serving while it is done.
"""
from __future__ import annotations

import asyncio
import json
import zlib
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql, sqlite

from .. import jsonio
from .database import Database
from .tables import designs, surveys, utcnow

# INSERT ... ON CONFLICT DO NOTHING is spelled the same on both databases, but SQLAlchemy builds it per dialect.
INSERTS = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}
# A survey takes a minute or two; one still marked running long after it started was cut off by a restart.
STALE_AFTER = timedelta(minutes=15)
COMPRESSION_LEVEL = 6


def survey_status(status: str, created_at: datetime, now: datetime) -> str:
    """A saved survey's status as the page should see it: 'failed' when a restart cut it off while it ran."""
    return "failed" if status == "running" and now - created_at > STALE_AFTER else status


def pack_state(state: dict) -> bytes:
    """A run's state as stored: zlib of compact JSON in UTF-8."""
    try:
        text = json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate in the data, which UTF-8 cannot hold: escape it instead
        text = json.dumps(state, separators=(",", ":")).encode("utf-8")
    return zlib.compress(text, COMPRESSION_LEVEL)


def unpack_state(blob: bytes) -> dict:
    return jsonio.loads(zlib.decompress(blob))


def started(
    run_id: str, request: dict, created_at: datetime, user_id: str | None = None, device_id: str | None = None,
) -> dict:
    """A survey's row as it starts: running, with no events yet."""
    return {
        "id": run_id, "created_at": created_at, "updated_at": created_at, "status": "running", "intent": request["intent"],
        "label": request["label"][:200], "lat": request["lat"], "lon": request["lon"], "request": request, "events": [],
        "user_id": user_id, "device_id": device_id,
    }


class SurveyStore:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    async def start(
        self, run_id: str, request: dict, created_at: datetime, *, user_id: str | None = None, device_id: str | None = None,
    ) -> None:
        """Records a survey as it starts: what the owner asked for, who asked (when signed in), from which browser,
        and no events yet."""
        async with self._engine.begin() as connection:
            await connection.execute(surveys.insert().values(**started(run_id, request, created_at, user_id, device_id)))

    async def finish(
        self, run_id: str, status: str, events: list[list], state: dict | None, headline: str | None = None,
        *, unsaved: dict | None = None,
    ) -> None:
        """Records how a survey ended: its status, every event it streamed, the run's final state (compressed) and its
        headline (the top concept's name, or the top gap). `unsaved` is the survey's start (start's arguments) when the
        database never saved it, as when it failed while the survey began: the row is then written whole."""
        values = {"status": status, "events": events, "state": await asyncio.to_thread(pack_state, state) if state else None}
        if headline:
            values["headline"] = headline[:200]
        async with self._engine.begin() as connection:
            result = await connection.execute(update(surveys).where(surveys.c.id == run_id).values(**values))
            if result.rowcount == 0 and unsaved is not None:
                row = {**started(run_id, **unsaved), **values}
                row.pop("updated_at")  # it ends now
                await connection.execute(surveys.insert().values(**row))

    async def get(self, run_id: str, *, with_state: bool = True) -> dict | None:
        """A survey as saved, its state unpacked (None while it runs); without its state when it is not needed."""
        columns = surveys.c if with_state else [column for column in surveys.c if column.name != "state"]
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(*columns).where(surveys.c.id == run_id))).mappings().first()
        if not row:
            return None
        found = dict(row)
        if found.get("state") is not None:
            found["state"] = await asyncio.to_thread(unpack_state, found["state"])
        return found

    async def save_design(self, run_id: str, idx: int, sheet: dict) -> None:
        """Keeps a concept's design sheet; when two requests design the same concept, the first sheet saved stays."""
        insert = INSERTS[self._engine.dialect.name](designs)
        async with self._engine.begin() as connection:
            await connection.execute(insert.values(survey_id=run_id, idx=idx, sheet=sheet).on_conflict_do_nothing())

    async def get_designs(self, run_id: str) -> dict[int, dict]:
        async with self._engine.connect() as connection:
            rows = await connection.execute(select(designs.c.idx, designs.c.sheet).where(designs.c.survey_id == run_id))
            return {idx: sheet for idx, sheet in rows}

    async def purge(self, older_than_days: int, keep: tuple[str, ...] = ()) -> int:
        """Deletes surveys older than this, with their design sheets, unless a signed-in user keeps them in My places or
        they are among `keep` (the examples anyone can open)."""
        cutoff = utcnow() - timedelta(days=older_than_days)
        condition = [surveys.c.created_at < cutoff, surveys.c.user_id.is_(None)]
        if keep:
            condition.append(surveys.c.id.not_in(keep))
        async with self._engine.begin() as connection:
            result = await connection.execute(delete(surveys).where(*condition))
        return result.rowcount
