"""Surveys and their design sheets in the database."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select, update
from sqlalchemy.dialects import postgresql, sqlite

from .database import Database
from .tables import campaigns, designs, kits, orders, surveys, utcnow

# INSERT ... ON CONFLICT DO NOTHING is spelled the same on both databases, but SQLAlchemy builds it per dialect.
INSERTS = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}


class SurveyStore:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    async def start(self, run_id: str, request: dict, created_at: datetime) -> None:
        """Records a survey as it starts: what the owner asked for, and no events yet."""
        async with self._engine.begin() as connection:
            await connection.execute(surveys.insert().values(
                id=run_id, created_at=created_at, updated_at=created_at, status="running", intent=request["intent"],
                label=request["label"][:200], lat=request["lat"], lon=request["lon"], request=request, events=[],
            ))

    async def finish(self, run_id: str, status: str, events: list[list], state: dict | None) -> None:
        """Records how a survey ended: its status, every event it streamed and the run's final state."""
        async with self._engine.begin() as connection:
            await connection.execute(
                update(surveys).where(surveys.c.id == run_id).values(status=status, events=events, state=state)
            )

    async def get(self, run_id: str) -> dict | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(surveys).where(surveys.c.id == run_id))).mappings().first()
        return dict(row) if row else None

    async def save_design(self, run_id: str, idx: int, sheet: dict) -> None:
        """Keeps a concept's design sheet; when two requests design the same concept, the first sheet saved stays."""
        insert = INSERTS[self._engine.dialect.name](designs)
        async with self._engine.begin() as connection:
            await connection.execute(insert.values(survey_id=run_id, idx=idx, sheet=sheet).on_conflict_do_nothing())

    async def get_designs(self, run_id: str) -> dict[int, dict]:
        async with self._engine.connect() as connection:
            rows = await connection.execute(select(designs.c.idx, designs.c.sheet).where(designs.c.survey_id == run_id))
            return {idx: sheet for idx, sheet in rows}

    async def purge(self, older_than_days: int) -> int:
        """Deletes surveys older than this, with their design sheets, unless an order or a campaign refers to them.

        Kits come with orders; they are checked too, so the purge can never break a foreign key and stop a startup.
        """
        cutoff = utcnow() - timedelta(days=older_than_days)
        async with self._engine.begin() as connection:
            result = await connection.execute(delete(surveys).where(
                surveys.c.created_at < cutoff,
                ~exists().where(orders.c.survey_id == surveys.c.id),
                ~exists().where(kits.c.survey_id == surveys.c.id),
                ~exists().where(campaigns.c.survey_id == surveys.c.id),
            ))
        return result.rowcount
