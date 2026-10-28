"""Launch kits: one per survey concept, built in the background (app.kits), kept and deleted with their survey."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .database import Database
from .tables import kits, surveys

KIT = (kits.c.token, kits.c.survey_id, kits.c.idx, kits.c.status, kits.c.name, kits.c.error, kits.c.created_at)


class KitStore:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    async def create(self, survey_id: str, idx: int, *, token: str, name: str) -> tuple[dict, bool]:
        """The concept's kit, and whether it is new: a kit building under `token`, or the one made before (one kit per
        concept, even when two requests ask at once). LookupError when the survey is not saved."""
        try:
            async with self._engine.begin() as connection:
                await connection.execute(kits.insert().values(
                    token=token, survey_id=survey_id, idx=idx, status="building", name=name[:200] or None,
                ))
        except IntegrityError:
            found = await self.for_concept(survey_id, idx)
            if found is None:  # not a second kit: the survey itself is missing
                raise LookupError(f"Survey {survey_id} is not saved") from None
            return found, False
        made = await self.kit(token, with_payload=False)
        if made is None:  # deleted with its survey in the meantime
            raise LookupError(f"Survey {survey_id} is not saved")
        return made, True

    async def kit(self, token: str, *, with_payload: bool = True) -> dict | None:
        columns = (*KIT, kits.c.payload) if with_payload else KIT
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(*columns).where(kits.c.token == token))).mappings().first()
        return dict(row) if row else None

    async def for_concept(self, survey_id: str, idx: int) -> dict | None:
        query = select(*KIT).where(kits.c.survey_id == survey_id, kits.c.idx == idx)
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).mappings().first()
        return dict(row) if row else None

    async def ready_for(self, survey_id: str) -> list[str]:
        """The tokens of a survey's ready kits, by concept."""
        query = select(kits.c.token).where(kits.c.survey_id == survey_id, kits.c.status == "ready").order_by(kits.c.idx)
        async with self._engine.connect() as connection:
            return list((await connection.execute(query)).scalars())

    async def owned_by(self, user_id: str, limit: int = 100) -> list[dict]:
        """The kits of the user's surveys, newest first."""
        query = (
            select(*KIT)
            .join(surveys, surveys.c.id == kits.c.survey_id)
            .where(surveys.c.user_id == user_id)
            .order_by(kits.c.created_at.desc())
            .limit(limit)
        )
        async with self._engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(query)).mappings()]

    async def building(self) -> list[str]:
        """The kits still building, such as those a restart cut off."""
        async with self._engine.connect() as connection:
            return list((await connection.execute(select(kits.c.token).where(kits.c.status == "building"))).scalars())

    async def rebuild(self, token: str) -> bool:
        """Sets a failed kit building again; False when it was not failed."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(kits).where(kits.c.token == token, kits.c.status == "failed").values(status="building", error=None)
            )
        return result.rowcount == 1

    async def save_payload(self, token: str, payload: dict) -> bool:
        """Replaces a ready kit's payload, as when its street map arrives after the kit was built (app.kits). False when
        the kit is gone or not ready."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(kits).where(kits.c.token == token, kits.c.status == "ready").values(payload=payload)
            )
        return result.rowcount == 1

    async def finish(
        self, token: str, *, payload: dict | None = None, error: str | None = None, name: str | None = None,
    ) -> bool:
        """Ends a build: ready with its payload, or failed with the reason. False when the kit is gone (its survey was
        deleted meanwhile) or no longer building."""
        values: dict[str, object] = (
            {"status": "failed", "error": error[:500]} if error else {"status": "ready", "payload": payload, "error": None}
        )
        if name:
            values["name"] = name[:200]
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(kits).where(kits.c.token == token, kits.c.status == "building").values(**values)
            )
        return result.rowcount == 1
