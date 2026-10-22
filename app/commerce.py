"""What Walk-in sells through PayPal, around the endpoints: money in minor units, PayPal's refusals as HTTP answers,
campaigns and pledges as app.payments.pledges sees them, and launch kits built in the background once paid."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .db import SurveyStore
from .db.kits import KitStore
from .payments import pledges
from .payments.paypal import ZERO_DECIMAL, PayPalClient, PayPalError, money
from .survey import design as designs
from .survey import kit as kits
from .survey.models import RunState, RunStore

if TYPE_CHECKING:
    from .main import Services

log = logging.getLogger("walkin")

# A campaign's status as the pages know it: "funded" (decided, collection under way) reads as partial until done.
PUBLIC_STATUS = {"funded": "partial"}
PROGRESS_KEYS = ("supporters", "goal", "remaining", "percent", "total", "funded")


class Problem(Exception):
    """An HTTP error whose JSON carries more than FastAPI's detail, such as {"detail": ..., "retry": true}."""

    def __init__(self, status: int, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.detail, self.extra = status, detail, extra


async def problem_response(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return JSONResponse({"detail": exc.detail, **exc.extra}, status_code=exc.status)


def iso(moment: datetime | None) -> str | None:
    """A time as the API writes it: ISO 8601 in UTC, to the second ('2026-10-22T14:03:00Z')."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else None


def minor(amount: str | Decimal | int, currency: str) -> int:
    """'19.00' USD -> 1900; whole units for currencies without cents."""
    value = Decimal(money(amount, currency))
    return int(value if currency.upper() in ZERO_DECIMAL else value * 100)


def major(units: int, currency: str) -> str:
    """1900 USD -> '19.00'."""
    return str(units) if currency.upper() in ZERO_DECIMAL else f"{Decimal(units) / 100:.2f}"


def paypal_client(request: Request) -> PayPalClient:
    client = request.app.state.services.paypal
    if client is None or not client.configured:
        raise HTTPException(503, "Payments are not set up on this server.")
    return client


def paypal_problem(exc: PayPalError, doing: str) -> Problem:
    """PayPal's refusal as an answer for the page. A declined card is the buyer's to fix in PayPal's buttons."""
    if exc.has("INSTRUMENT_DECLINED"):
        return Problem(402, "PayPal declined that payment method. Choose another one to continue.", retry=True)
    if exc.has("ORDER_NOT_APPROVED", "PAYER_ACTION_REQUIRED"):
        return Problem(409, "The payment was not approved in PayPal yet.")
    if exc.retryable or exc.status in (401, 403):
        return Problem(502, f"PayPal could not {doing} right now. Try again in a moment.")
    code = exc.issues[0] if exc.issues else exc.name
    return Problem(400, f"PayPal could not {doing} ({code}).")


# Campaigns and pledges, from their rows

def campaign_of(row: dict) -> pledges.Campaign:
    return pledges.Campaign(
        id=row["id"], amount=major(row["amount_cents"], row["currency"]), goal=row["goal_count"], deadline=row["deadline"],
        currency=row["currency"], status=row["status"], closed_at=row["closed_at"], funded=row["funded"],
    )


def pledge_of(row: dict, currency: str) -> pledges.Pledge:
    return pledges.Pledge(
        id=row["id"], amount=major(row["amount_cents"], currency), currency=currency, status=row["status"],
        order_id=row["order_id"], payer_id=row["payer_id"], authorization_id=row["authorization_id"],
        authorized_at=row["authorized_at"], expires_at=row["expires_at"], reauthorization_id=row["reauthorization_id"],
        reauthorized_at=row["reauthorized_at"], capture_id=row["capture_id"], error=row["error"],
    )


def public_status(status: str) -> str:
    return PUBLIC_STATUS.get(status, status)


def public_progress(progress: dict) -> dict:
    return {key: progress[key] for key in PROGRESS_KEYS}


# Launch kits

def kit_custom_id(user_id: str, survey_id: str, index: int) -> str:
    """The custom_id of a kit order: who buys which concept."""
    return f"kit:{survey_id}:{index}:{user_id}"


def pledge_custom_id(campaign_id: str, pledge_id: str) -> str:
    return f"pledge:{campaign_id}:{pledge_id}"


class KitUnavailable(RuntimeError):
    """A paid kit that cannot be built; the message says why, in plain words."""


async def designed(services: Services, surveys: SurveyStore, run: RunState, index: int) -> dict:
    """The concept's design sheet, designed now (as POST /api/design does) when it has none."""
    sheet = run.designs.get(index)
    if sheet is not None:
        return sheet
    made = await designs.design_concept(services.llm, services.images, run, index, services.qloo, services.answers)
    sheet = run.designs.setdefault(index, made)
    try:
        await surveys.save_design(run.id, index, sheet)
    except Exception:
        log.warning("Could not save design sheet %d of survey %s", index, run.id, exc_info=True)
    return sheet


class KitBuilder:
    """Builds paid kits in the background: the concept's design sheet first when it has none, then kit.build_kit.

    One build per kit at a time. stop() cancels the builds still running; a kit left building is built again at the
    next start (resume), so a restart never loses a paid kit.
    """

    def __init__(self, store: KitStore, runs: RunStore, surveys: SurveyStore, services: Services) -> None:
        self._store, self._runs, self._surveys, self._services = store, runs, surveys, services
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, token: str) -> None:
        if token in self._tasks:
            return
        task = asyncio.create_task(self._build(token))
        self._tasks[token] = task

        def finished(done: asyncio.Task) -> None:
            if self._tasks.get(token) is done:
                del self._tasks[token]

        task.add_done_callback(finished)

    async def resume(self) -> int:
        """Starts again every kit a restart cut off."""
        tokens = await self._store.building()
        for token in tokens:
            self.start(token)
        return len(tokens)

    async def wait(self) -> None:
        """Waits for the builds running now."""
        await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _build(self, token: str) -> None:
        kit = await self._store.kit(token)
        if kit is None or kit["status"] != "building":
            return
        try:
            payload = await self._make(kit["survey_id"], kit["idx"])
        except KitUnavailable as exc:
            await self._store.finish(token, error=str(exc))
        except Exception:
            log.error("Kit %s failed to build", token, exc_info=True)
            await self._store.finish(token, error="Something went wrong while building the kit. Try again; you are not charged twice.")
        else:
            await self._store.finish(token, payload=payload, name=payload.get("concept", {}).get("name"))

    async def _make(self, survey_id: str, index: int) -> dict:
        run = await self._runs.fetch(survey_id)
        if run is None or not 0 <= index < len(run.concepts):
            raise KitUnavailable("The survey this kit was bought for is no longer saved, so the kit cannot be built. Ask for a refund.")
        services = self._services
        sheet = await designed(services, self._surveys, run, index)
        return await kits.build_kit(services.llm, run, index, sheet, services.answers)
