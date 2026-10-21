"""Cross-domain taste of the people near the site: what fans of a category also love."""
from __future__ import annotations

from .. import engine
from ..qloo import QlooClient
from .models import RunState


async def fans_of(q: QlooClient, run: RunState, genre_id: str) -> dict:
    """What people near the site who love a genre also love; fetched once per run."""
    if genre_id not in run.fans:
        run.fans[genre_id] = await engine.fan_taste(q, run.site.lat, run.site.lon, genre_id)
    return run.fans[genre_id]
