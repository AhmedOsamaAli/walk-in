"""The experience around a concept: what to play, screen and host, from what the neighborhood over-indexes on.

Two Qloo signals exist and only one is local. The neighborhood's signature taste (what people within 1.5 km, or as far
as a big area reaches, rank much higher than same-size areas around do) compares places with places, so it is local by
construction. What fans
of a category also love is mostly that category's audience at large, and for some categories (live music venues,
breweries, coffee shops) Qloo ignores the category and returns the area's general ranking. So the plan is built from
the signature taste, and fan taste is only used where it is specific, as evidence of fit.
"""
from __future__ import annotations

import re
from datetime import date

from .. import engine, scoring
from ..qloo import QlooClient
from .evidence import aged
from .models import RunState

# Share of the fans' top names that are just the area's own top names, above which Qloo ignored the category.
IGNORED_SHARE = 0.8
TALK_PLACES = re.compile(r"\b(cafe|café|coffee|tea|book|bookstore|wine)\b", re.IGNORECASE)
LICENSING = (
    "Playing recorded music or screening films and shows for guests needs public performance licenses from the local "
    "rights organizations; budget for them before programming."
)
# The basis of a walk-sized survey for everyone; basis(run) gives each run's own.
BASIS = "What people within 1.5 km over-index on compared with same-size areas a few kilometres around (Qloo)."


def basis(run: RunState) -> str:
    """Where the signature taste comes from in this run: the taste neighborhood grows with a big area (engine.taste_m),
    its comparison areas lie farther out (engine.reference_distance), and an age focus leans both toward that age."""
    radius = engine.taste_m(run.catchment) if run.catchment else engine.TASTE_M
    within = f"{round(radius / 1000, 1):g} km" if radius < 10_000 else f"{round(radius / 1000)} km"
    away = engine.reference_distance(radius)
    around = "a few kilometres around" if away <= 6000 else f"about {round(away / 1000)} km away"
    return f"What people{aged(run.site.ages)} within {within} over-index on compared with same-size areas {around} (Qloo)."


async def fans_of(q: QlooClient, run: RunState, genre_id: str) -> dict:
    """What people who love a genre also love; fetched once per run, with whether it is specific to the category."""
    if genre_id not in run.fans:
        radius = engine.taste_m(run.catchment) if run.catchment else engine.TASTE_M
        fans = await engine.fan_taste(q, run.site.lat, run.site.lon, genre_id, ages=run.site.ages, radius=radius)
        fans["specific"] = is_specific(fans, run.taste)
        run.fans[genre_id] = fans
    return run.fans[genre_id]


def is_specific(fans: dict, taste: dict) -> bool:
    """False when the fans' top names are mostly the area's own top names: Qloo ignored the category."""
    area = {card["id"] for card in taste.get("artists", []) + taste.get("brands", [])}
    top = [card["id"] for card in fans.get("artists", [])[:10] + fans.get("brands", [])[:10]]
    if not top or not area:
        return bool(top)
    return sum(1 for item in top if item in area) / len(top) < IGNORED_SHARE


def plan(run: RunState, genre: str, this_year: int | None = None) -> dict | None:
    """Soundtrack for every concept, a screen for bars and venues, talks for bars, venues and cafés."""
    this_year = this_year or date.today().year
    taste = run.taste
    kind = scoring.genre_kind(genre)

    def cards(domain: str, limit: int) -> list[dict]:
        # An artist who started within ten years is a new voice; a film or show is new for about two years.
        new_within = 10 if domain == "artists" else 2
        out = []
        for card in taste.get(f"distinctive_{domain}", [])[:limit]:
            item = {k: card[k] for k in ("id", "name", "image", "year", "since") if card.get(k) is not None}
            label = scoring.era(card.get("since") or card.get("year"), this_year, new_within)
            if label:
                item["era"] = label
            out.append(item)
        return out

    sections = {"soundtrack": cards("artists", 8)}
    if kind in ("bar", "venue"):
        sections["screen"] = cards("movies", 4) + cards("tv", 4)
    if kind in ("bar", "venue") or TALK_PLACES.search(genre):
        sections["talks"] = cards("podcasts", 4)
    sections = {name: items for name, items in sections.items() if items}
    if not sections:
        return None
    return {**sections, "basis": basis(run), "licensing": LICENSING if set(sections) & {"soundtrack", "screen"} else None}
