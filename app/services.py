"""The outside world the app talks to, in one place: Qloo, the routing service (walks and drives), OpenStreetMap,
Nominatim, Google's sign-in keys, the AI chain, the saved AI answers and PayPal. app.main builds the real ones; tests
swap in fakes."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import auth
from .answers import AnswerCache
from .catchment import CatchmentService
from .geocode import Geocoder
from .llm import LLM
from .osm import OsmClient
from .payments.paypal import PayPalClient
from .qloo import QlooClient


@dataclass
class Services:
    """Everything the endpoints talk to; swapped for fakes in tests."""

    qloo: QlooClient
    walker: CatchmentService
    llm: LLM
    geocoder: Geocoder
    answers: AnswerCache = field(default_factory=lambda: AnswerCache(None))
    osm: OsmClient | None = None  # the OpenStreetMap cross-check of the gaps; without it, rows say it is off
    google: auth.GoogleKeys = field(default_factory=auth.GoogleKeys)
    paypal: PayPalClient | None = None  # Walk-in Founders' pledges and payouts; without it nobody can pledge

    async def aclose(self) -> None:
        if self.osm is not None:
            await self.osm.aclose()
        if self.paypal is not None:
            await self.paypal.aclose()
        for service in (self.qloo, self.walker, self.geocoder, self.google):
            await service.aclose()
