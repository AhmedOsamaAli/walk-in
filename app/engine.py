"""Evidence gathering: each function answers one question about a site using Qloo."""
from __future__ import annotations

import asyncio

from . import scoring
from .geo import point_wkt
from .qloo import QlooClient

WALK_M = 800  # roughly a 10-minute walk
TASTE_M = 1500  # neighborhood used for brand/artist taste
METRO_M = 25_000  # wider baseline the neighborhood is compared against
FAVORITES_M = 15_000  # where locals' favorite places are searched for
GAP_GENRES = 8


async def nearby_places(
    q: QlooClient, lat: float, lon: float, radius: int = WALK_M, tag: str | None = None, take: int = 50, offset: int = 0
) -> list[dict]:
    params = {
        "filter.type": "urn:entity:place",
        "filter.location": point_wkt(lat, lon),
        "filter.location.radius": radius,
        "take": take,
    }
    if tag:
        params["filter.tags"] = tag
    if offset:
        params["offset"] = offset
    return scoring.entities(await q.insights(params))


async def scan_block(q: QlooClient, lat: float, lon: float) -> list[dict]:
    """Up to 100 places within walking distance, deduplicated."""
    first, second = await asyncio.gather(nearby_places(q, lat, lon), nearby_places(q, lat, lon, offset=50))
    seen: set[str] = set()
    places = []
    for place in first + second:
        pid = scoring.item_id(place)
        if pid and pid not in seen:
            seen.add(pid)
            places.append(place)
    return places


async def demand_genres(q: QlooClient, lat: float, lon: float) -> tuple[list[dict], list[str]]:
    """Place genres people around the site engage with most, split into business genres and taste cues."""
    data = await q.insights({
        "filter.type": "urn:tag",
        "filter.tag.types": "urn:tag:genre:place",
        "signal.location": point_wkt(lat, lon),
        "signal.location.radius": WALK_M,
        "take": 50,
    })
    business, cues = [], []
    for tag in scoring.tags(data):
        name, tid = tag.get("name"), scoring.item_id(tag)
        if not name or not tid:
            continue
        if scoring.is_taste_cue(name):
            cues.append(name)
        elif scoring.is_business_genre(name):
            business.append({"id": tid, "name": name})
    for rank, genre in enumerate(business, 1):
        genre["rank"] = rank
    return business, cues[:6]


async def locals_favorites(q: QlooClient, lat: float, lon: float, tag: str, take: int = 10) -> list[dict]:
    """Places of one genre that people around the site love, anywhere within the metro."""
    return scoring.entities(await q.insights({
        "filter.type": "urn:entity:place",
        "signal.location": point_wkt(lat, lon),
        "signal.location.radius": WALK_M,
        "filter.tags": tag,
        "filter.location": point_wkt(lat, lon),
        "filter.location.radius": FAVORITES_M,
        "take": take,
    }))


async def genre_gap(q: QlooClient, lat: float, lon: float, genre: dict, position: int, total: int) -> dict:
    nearby, favorites = await asyncio.gather(
        nearby_places(q, lat, lon, tag=genre["id"]),
        locals_favorites(q, lat, lon, genre["id"]),
    )
    row = scoring.gap_row(genre["id"], genre["name"], position, total, nearby, favorites, (lat, lon), WALK_M)
    row["demand_rank"] = genre["rank"]
    row["competitors"] = [scoring.place_card(p, (lat, lon)) for p in nearby[:8]]
    row["favorites"] = [scoring.place_card(p, (lat, lon)) for p in favorites]
    row["_favorite_entities"] = favorites
    row["_nearby_entities"] = nearby
    return row


async def gap_table(q: QlooClient, lat: float, lon: float, genres: list[dict], focus: str = "any") -> list[dict]:
    """Rank the neighborhood's top genres by how underserved they are within walking distance."""
    candidates = [g for g in genres if scoring.matches_focus(g["name"], focus)][:GAP_GENRES]
    rows = await asyncio.gather(
        *(genre_gap(q, lat, lon, g, position, len(candidates)) for position, g in enumerate(candidates, 1))
    )
    return sorted(rows, key=lambda r: -r["gap_score"])


async def _ranked(q: QlooClient, entity_type: str, lat: float, lon: float, radius: int, take: int = 30) -> list[dict]:
    return scoring.entities(await q.insights({
        "filter.type": entity_type,
        "filter.popularity.min": 0.1,
        "signal.location": point_wkt(lat, lon),
        "signal.location.radius": radius,
        "take": take,
    }))


async def local_taste(q: QlooClient, lat: float, lon: float) -> dict:
    brands, brands_metro, artists, artists_metro = await asyncio.gather(
        _ranked(q, "urn:entity:brand", lat, lon, TASTE_M),
        _ranked(q, "urn:entity:brand", lat, lon, METRO_M),
        _ranked(q, "urn:entity:artist", lat, lon, TASTE_M),
        _ranked(q, "urn:entity:artist", lat, lon, METRO_M),
    )
    return {
        "brands": [scoring.entity_card(e) for e in brands if scoring.is_safe_name(e.get("name"))][:12],
        "distinctive_brands": [scoring.entity_card(e) for e in scoring.distinctive(brands, brands_metro)],
        "artists": [scoring.entity_card(e) for e in artists if scoring.is_safe_name(e.get("name"))][:12],
        "distinctive_artists": [scoring.entity_card(e) for e in scoring.distinctive(artists, artists_metro)],
    }


async def crowd_demographics(q: QlooClient, places: list[dict]) -> dict | None:
    """Age and gender skew of the crowd, read through the area's most popular places."""
    ranked = sorted(places, key=lambda p: -(p.get("popularity") or 0))
    ids = [scoring.item_id(p) for p in ranked[:5] if scoring.item_id(p)]
    if not ids:
        return None
    data = await q.insights({"filter.type": "urn:demographics", "signal.interests.entities": ",".join(ids)})
    results = data.get("results") or {}
    return scoring.average_demographics(results.get("demographics") or [])


async def genre_heatmap(q: QlooClient, lat: float, lon: float, tag: str, radius: int = 3000) -> list[dict]:
    data = await q.insights({
        "filter.type": "urn:heatmap",
        "filter.location": point_wkt(lat, lon),
        "filter.location.radius": radius,
        "signal.interests.tags": tag,
    })
    cells = ((data.get("results") or {}).get("heatmap")) or []
    return [
        {
            "lat": c["location"]["latitude"],
            "lon": c["location"]["longitude"],
            "affinity": round(c["query"].get("affinity_rank", c["query"].get("affinity", 0)), 3),
        }
        for c in cells
        if c.get("location") and c.get("query")
    ]
