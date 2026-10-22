"""PayPal webhook events, kept once each by PayPal's event id."""
from __future__ import annotations

from sqlalchemy import delete

from .database import Database
from .surveys import INSERTS
from .tables import paypal_events


class EventStore:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    async def record(self, event_id: str, event_type: str, resource_id: str | None, payload: dict) -> bool:
        """Keeps an event; False when it was kept before (PayPal delivers an event again until it is acknowledged)."""
        insert = INSERTS[self._engine.dialect.name](paypal_events)
        async with self._engine.begin() as connection:
            result = await connection.execute(insert.values(
                id=event_id[:64], event_type=event_type[:64], resource_id=(resource_id or None) and resource_id[:64],
                payload=payload,
            ).on_conflict_do_nothing())
        return result.rowcount == 1

    async def forget(self, event_id: str) -> None:
        """Drops an event whose handling failed, so PayPal's next delivery is handled again."""
        async with self._engine.begin() as connection:
            await connection.execute(delete(paypal_events).where(paypal_events.c.id == event_id[:64]))
