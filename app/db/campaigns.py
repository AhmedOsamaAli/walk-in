"""Pledge campaigns and their pledges."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import exists, or_, select, update

from .database import Database
from .tables import campaigns, pledges

# A campaign still running or still collecting; the others are settled for good.
ACTIVE = ("open", "funded", "partial")


class CampaignStore:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    async def create(self, **values: object) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(campaigns.insert().values(**values))

    async def get(self, campaign_id: str) -> dict | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(campaigns).where(campaigns.c.id == campaign_id))).mappings().first()
        return dict(row) if row else None

    async def for_kit(self, kit_token: str, active: bool = False) -> dict | None:
        """The kit's newest campaign (only an open or collecting one with `active`)."""
        query = select(campaigns).where(campaigns.c.kit_token == kit_token)
        if active:
            query = query.where(campaigns.c.status.in_(ACTIVE))
        async with self._engine.connect() as connection:
            row = (await connection.execute(query.order_by(campaigns.c.created_at.desc()))).mappings().first()
        return dict(row) if row else None

    async def owned_by(self, user_id: str, limit: int = 100) -> list[dict]:
        query = select(campaigns).where(campaigns.c.user_id == user_id).order_by(campaigns.c.created_at.desc()).limit(limit)
        async with self._engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(query)).mappings()]

    async def update(self, campaign_id: str, **values: object) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(update(campaigns).where(campaigns.c.id == campaign_id).values(**values))

    async def due(self, now: datetime) -> list[str]:
        """Campaigns to settle now: open ones past their close, and any other not settled for good, or settled with a
        hold left over (it came in late), oldest deadline first."""
        held = exists().where(pledges.c.campaign_id == campaigns.c.id, pledges.c.status == "authorized")
        closed = or_(campaigns.c.deadline <= now, campaigns.c.closed_at <= now)
        query = select(campaigns.c.id).where(or_(
            (campaigns.c.status == "open") & closed,
            campaigns.c.status == "funded",
            (campaigns.c.status != "open") & held,
        )).order_by(campaigns.c.deadline)
        async with self._engine.connect() as connection:
            return list((await connection.execute(query)).scalars())

    # Pledges

    async def add_pledge(self, **values: object) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(pledges.insert().values(**values))

    async def pledges(self, campaign_ids: Iterable[str]) -> list[dict]:
        ids = list(campaign_ids)
        if not ids:
            return []
        query = select(pledges).where(pledges.c.campaign_id.in_(ids)).order_by(pledges.c.created_at, pledges.c.id)
        async with self._engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(query)).mappings()]

    async def pledge(self, **match: str) -> dict | None:
        """The pledge whose columns equal `match`, such as campaign_id and order_id."""
        query = select(pledges).where(*(pledges.c[column] == value for column, value in match.items()))
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).mappings().first()
        return dict(row) if row else None

    async def pledge_by_authorization(self, authorization_id: str) -> dict | None:
        """The pledge holding this authorization, original or renewed."""
        query = select(pledges).where(or_(
            pledges.c.authorization_id == authorization_id, pledges.c.reauthorization_id == authorization_id,
        ))
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).mappings().first()
        return dict(row) if row else None

    async def update_pledge(self, pledge_id: str, *, only: tuple[str, ...] = (), **values: object) -> bool:
        """Changes a pledge; with `only`, just while its status is one of them. False when nothing changed."""
        query = update(pledges).where(pledges.c.id == pledge_id)
        if only:
            query = query.where(pledges.c.status.in_(only))
        async with self._engine.begin() as connection:
            result = await connection.execute(query.values(**values))
        return result.rowcount == 1

    async def save(self, campaign_id: str, campaign: dict, changes: dict[str, dict]) -> None:
        """Stores a settlement in one transaction: the campaign's new values and each changed pledge's."""
        async with self._engine.begin() as connection:
            await connection.execute(update(campaigns).where(campaigns.c.id == campaign_id).values(**campaign))
            for pledge_id, values in changes.items():
                await connection.execute(update(pledges).where(pledges.c.id == pledge_id).values(**values))
