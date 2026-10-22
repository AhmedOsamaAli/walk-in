"""Launch kit orders and the kits they paid for."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .database import Database
from .tables import kits, orders

KIT = (
    kits.c.token, kits.c.order_id, kits.c.survey_id, kits.c.idx, kits.c.status, kits.c.user_id, kits.c.name,
    kits.c.error, kits.c.created_at,
)


class KitStore:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    async def add_order(
        self, *, order_id: str, user_id: str, survey_id: str, idx: int, amount_cents: int, currency: str, environment: str,
    ) -> None:
        async with self._engine.begin() as connection:
            await connection.execute(orders.insert().values(
                id=order_id, user_id=user_id, survey_id=survey_id, idx=idx, product="launch_kit",
                amount_cents=amount_cents, currency=currency, status="created", environment=environment,
            ))

    async def order(self, order_id: str) -> dict | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(orders).where(orders.c.id == order_id))).mappings().first()
        return dict(row) if row else None

    async def order_by_capture(self, capture_id: str) -> dict | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(orders).where(orders.c.capture_id == capture_id))).mappings().first()
        return dict(row) if row else None

    async def mark_order(self, order_id: str, status: str, *, unless: tuple[str, ...] = (), **values: object) -> None:
        """Sets an order's status (and capture_id or payer_id), unless it already has one of the `unless` statuses."""
        query = update(orders).where(orders.c.id == order_id)
        if unless:
            query = query.where(orders.c.status.not_in(unless))
        async with self._engine.begin() as connection:
            await connection.execute(query.values(status=status, **values))

    async def deliver(self, order_id: str, *, token: str, name: str, capture_id: str | None, payer_id: str | None) -> dict:
        """Marks a paid order completed and creates its kit, building. Delivering an order twice, even at once, gives
        the kit made the first time."""
        try:
            async with self._engine.begin() as connection:
                await connection.execute(update(orders).where(orders.c.id == order_id).values(
                    status="completed", capture_id=capture_id, payer_id=payer_id,
                ))
                order = (await connection.execute(select(orders).where(orders.c.id == order_id))).mappings().one()
                await connection.execute(kits.insert().values(
                    token=token, order_id=order_id, survey_id=order["survey_id"], idx=order["idx"], status="building",
                    user_id=order["user_id"], name=name[:200],
                ))
        except IntegrityError:  # the kit exists already: kits.order_id is unique
            pass
        kit = await self.kit_for_order(order_id)
        if kit is None:
            raise LookupError(f"Order {order_id} has no kit")
        return kit

    async def kit(self, token: str) -> dict | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(*KIT, kits.c.payload).where(kits.c.token == token))).mappings().first()
        return dict(row) if row else None

    async def kit_for_order(self, order_id: str) -> dict | None:
        async with self._engine.connect() as connection:
            row = (await connection.execute(select(*KIT).where(kits.c.order_id == order_id))).mappings().first()
        return dict(row) if row else None

    async def owned(self, user_id: str, survey_id: str, idx: int) -> dict | None:
        """The user's kit for this concept, unless it was refunded."""
        query = (
            select(*KIT)
            .where(kits.c.user_id == user_id, kits.c.survey_id == survey_id, kits.c.idx == idx, kits.c.status != "refunded")
            .order_by(kits.c.created_at.desc())
        )
        async with self._engine.connect() as connection:
            row = (await connection.execute(query)).mappings().first()
        return dict(row) if row else None

    async def owned_by(self, user_id: str, limit: int = 100) -> list[dict]:
        query = select(*KIT).where(kits.c.user_id == user_id).order_by(kits.c.created_at.desc()).limit(limit)
        async with self._engine.connect() as connection:
            return [dict(row) for row in (await connection.execute(query)).mappings()]

    async def building(self) -> list[str]:
        async with self._engine.connect() as connection:
            return list((await connection.execute(select(kits.c.token).where(kits.c.status == "building"))).scalars())

    async def rebuild(self, token: str) -> bool:
        """Sets a failed kit building again; False when it was not failed."""
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(kits).where(kits.c.token == token, kits.c.status == "failed").values(status="building", error=None)
            )
        return result.rowcount == 1

    async def finish(self, token: str, *, payload: dict | None = None, error: str | None = None, name: str | None = None) -> bool:
        """Ends a build: ready with its payload, or failed with the reason. A kit refunded meanwhile stays refunded."""
        values: dict[str, object] = {"status": "failed", "error": error[:500]} if error else {"status": "ready", "payload": payload, "error": None}
        if name:
            values["name"] = name[:200]
        async with self._engine.begin() as connection:
            result = await connection.execute(
                update(kits).where(kits.c.token == token, kits.c.status == "building").values(**values)
            )
        return result.rowcount == 1

    async def refund(self, order_id: str) -> None:
        """The order was refunded: so is its kit."""
        async with self._engine.begin() as connection:
            await connection.execute(update(orders).where(orders.c.id == order_id).values(status="refunded"))
            await connection.execute(update(kits).where(kits.c.order_id == order_id).values(status="refunded"))
