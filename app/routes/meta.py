"""The server's own facts: whether it is up and what it can reach (GET /api/health, which never reads the database,
so the keep-awake visits leave Neon asleep), and the preset sites the first screen offers (GET /api/presets)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, Response

from .. import cache_policy, schemas

if TYPE_CHECKING:
    from ..services import Services

router = APIRouter(prefix="/api")

PRESETS = [
    {"id": "ues", "label": "Upper East Side, Manhattan", "lat": 40.7736, "lon": -73.9566,
     "blurb": "Quiet residential blocks whose favorite spots are all downtown"},
    {"id": "williamsburg", "label": "Williamsburg, Brooklyn", "lat": 40.7145, "lon": -73.9580,
     "blurb": "Bars and brunch everywhere. What is still missing?"},
    {"id": "les", "label": "Lower East Side, Manhattan", "lat": 40.7183, "lon": -73.9884,
     "blurb": "Dense, young and nocturnal"},
    {"id": "east_austin", "label": "East Austin, Texas", "lat": 30.2622, "lon": -97.7247,
     "blurb": "A fast-changing neighborhood beyond New York"},
    {"id": "zamalek", "label": "Zamalek, Cairo", "lat": 30.0626, "lon": 31.2197,
     "blurb": "Works beyond the US: Cairo's island district"},
]


@router.get("/health", response_model=schemas.Health)
async def health(request: Request) -> dict:
    services: Services = request.app.state.services
    llm = services.llm
    return {
        "ok": True,
        "qloo": services.qloo.configured,
        "llm": llm.enabled,
        "model": llm.model if llm.enabled else None,
        "models": llm.models if llm.enabled else [],
        "resting": llm.resting() if llm.enabled else {},
    }


@router.get("/presets", response_model=list[schemas.Preset])
async def presets(response: Response) -> list[dict]:
    response.headers["Cache-Control"] = cache_policy.STATIC
    return PRESETS
