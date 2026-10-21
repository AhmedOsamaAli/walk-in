"""Evidence gathering: each function answers one question about a site using Qloo."""
from __future__ import annotations

import asyncio
import math

from . import scoring
from .catchment import Catchment
from .geo import point_wkt
from .qloo import QlooClient

TASTE_M = 1500  # neighborhood used for brand and artist taste
METRO_M = 20_000  # the wider city, used for the city's own favorite places
FAVORITES_M = 15_000  # where locals' favorite places are searched for
MIN_AROUND_M = 900  # smallest "surrounding area" used to predict supply
GAP_GENRES = 8
REF_BEARINGS = (0, 60, 120, 180, 240, 300)
TASTE_REF_BEARINGS = (30, 150, 270)
TASTE_DOMAINS = {
    "brands": "urn:entity:brand",
    "artists": "urn:entity:artist",
    "movies": "urn:entity:movie",
    "tv": "urn:entity:tv_show",
    "podcasts": "urn:entity:podcast",
}


def around_radius(catchment: Catchment) -> int:
    return max(MIN_AROUND_M, round(2 * catchment.radius_m))


def offset_point(lat: float, lon: float, distance_m: float, bearing_deg: float) -> tuple[float, float]:
    d_lat = distance_m * math.cos(math.radians(bearing_deg)) / 111_320
    d_lon = distance_m * math.sin(math.radians(bearing_deg)) / (111_320 * math.cos(math.radians(lat)))
    return lat + d_lat, lon + d_lon


def reference_points(lat: float, lon: float, radius_m: float, bearings=REF_BEARINGS) -> list[tuple[float, float]]:
    """Same-size comparison areas a few kilometres away, used instead of the whole city to avoid scale bias."""
    distance = max(2500.0, 3.5 * radius_m)
    return [offset_point(lat, lon, distance, bearing) for bearing in bearings]


async def places_in(q: QlooClient, location: dict, tag: str | None = None, take: int = 50, offset: int = 0) -> list[dict]:
    params = {"filter.type": "urn:entity:place", **location, "take": take}
    if tag:
        params["filter.tags"] = tag
    if offset:
        params["offset"] = offset
    return scoring.entities(await q.insights(params))


def walk_filter(catchment: Catchment) -> dict:
    return {"filter.location": catchment.wkt, "filter.location.radius": 0}


def circle_filter(lat: float, lon: float, radius: int) -> dict:
    return {"filter.location": point_wkt(lat, lon), "filter.location.radius": radius}


async def scan_block(q: QlooClient, catchment: Catchment) -> list[dict]:
    """Up to 100 places inside the walking catchment, deduplicated."""
    location = walk_filter(catchment)
    first, second = await asyncio.gather(places_in(q, location), places_in(q, location, offset=50))
    seen: set[str] = set()
    places = []
    for place in first + second:
        pid = scoring.item_id(place)
        if pid and pid not in seen:
            seen.add(pid)
            places.append(place)
    return places


async def _genre_ranking(q: QlooClient, signal: dict) -> list[dict]:
    data = await q.insights({"filter.type": "urn:tag", "filter.tag.types": "urn:tag:genre:place", **signal, "take": 50})
    return [tag for tag in scoring.tags(data) if tag.get("name") and scoring.item_id(tag)]


async def demand_genres(q: QlooClient, catchment: Catchment) -> tuple[list[dict], list[str]]:
    """Place genres the people in the catchment engage with, ranked here and in same-size areas around."""
    radius = max(300, round(catchment.radius_m))
    local, *references = await asyncio.gather(
        _genre_ranking(q, {"signal.location": catchment.wkt}),
        *(
            _genre_ranking(q, {"signal.location": point_wkt(lat, lon), "signal.location.radius": radius})
            for lat, lon in reference_points(catchment.lat, catchment.lon, catchment.radius_m)
        ),
    )
    reference_ranks = []
    for reference in references:
        business = [tag for tag in reference if scoring.is_business_genre(tag["name"])]
        if business:
            reference_ranks.append({scoring.item_id(tag): rank for rank, tag in enumerate(business, 1)})
    business, cues = [], []
    for tag in local:
        name = tag["name"]
        if scoring.is_taste_cue(name):
            cues.append(name)
        elif scoring.is_business_genre(name):
            business.append({"id": scoring.item_id(tag), "name": name})
    for rank, genre in enumerate(business, 1):
        genre["rank"] = rank
        genre["ref_rank"] = (
            scoring.reference_rank([ranks.get(genre["id"]) for ranks in reference_ranks])
            if len(reference_ranks) >= 3 else None
        )
    return business, cues[:6]


async def genre_evidence(q: QlooClient, catchment: Catchment, genre: dict) -> dict:
    lat, lon = catchment.lat, catchment.lon
    favorites_area = circle_filter(lat, lon, FAVORITES_M)
    nearby, around, local_favorites, city_favorites = await asyncio.gather(
        places_in(q, walk_filter(catchment), tag=genre["id"]),
        places_in(q, circle_filter(lat, lon, around_radius(catchment)), tag=genre["id"]),
        places_in(q, {"signal.location": catchment.wkt, **favorites_area}, tag=genre["id"], take=20),
        places_in(
            q,
            {"signal.location": point_wkt(lat, lon), "signal.location.radius": METRO_M, **favorites_area},
            tag=genre["id"],
            take=20,
        ),
    )
    kind, favorites = scoring.split_favorites(local_favorites, city_favorites)
    row = scoring.gap_signals(
        genre["id"], genre["name"], genre["rank"], genre.get("ref_rank"),
        nearby, around, favorites, kind, scoring.storefront_share(local_favorites[:10]),
        (lat, lon), catchment.contains,
    )
    row["competitors"] = [scoring.place_card(p, (lat, lon)) for p in nearby[:8]]
    row["favorites"] = [
        {**scoring.place_card(p, (lat, lon)), "within_walk": bool(loc and catchment.contains(*loc))}
        for p, loc in ((p, scoring.place_location(p)) for p in favorites)
    ]
    row["city_favorites"] = [p.get("name") for p in city_favorites[:6] if p.get("name")]
    row["_favorite_entities"] = favorites
    row["_nearby_entities"] = nearby
    return row


async def gap_table(q: QlooClient, catchment: Catchment, genres: list[dict], focus: str = "any") -> list[dict]:
    """Rank the neighborhood's top genres by how underserved they are within the walking catchment."""
    candidates = [genre for genre in genres if scoring.matches_focus(genre["name"], focus)][:GAP_GENRES]
    rows = await asyncio.gather(*(genre_evidence(q, catchment, genre) for genre in candidates))
    around_area = math.pi * around_radius(catchment) ** 2
    return scoring.score_gaps(list(rows), catchment.area_m2, around_area)


async def find_genre(q: QlooClient, ranked: list[dict], query: str) -> tuple[dict | None, str | None]:
    """Resolve free text ('bakeries', 'board game cafe') to a storefront place genre, or say why it cannot.

    Genres locals already rank keep their local and reference ranks; others come from Qloo's tag search and are
    marked unranked, which is itself evidence of weak local demand. A search result only counts when its words match
    the query's (exactly, more specific or broader): "art gallery" must not become "Aboriginal art gallery".
    """
    wanted = _normalize_genre(query)
    exact = next(
        (genre for genre in ranked if _normalize_genre(genre["name"]).replace(" ", "") == wanted.replace(" ", "")), None,
    )
    if exact:
        return exact, None
    data = await q.tags({"filter.query": query.strip()[:60], "filter.tag.types": "urn:tag:genre:place", "take": 10})
    best = None
    for position, tag in enumerate(scoring.tags(data)):
        tag_id, name = scoring.tag_id(tag), tag.get("name")
        quality = _match_quality(wanted, _normalize_genre(name)) if tag_id and name else 0
        if quality and (best is None or (-quality, len(name.split()), position) < best[0]):
            best = ((-quality, len(name.split()), position), tag_id, name)
    if best is None:
        return None, f"Qloo has no storefront category matching '{query}'."
    _, tag_id, name = best
    if name.strip().lower() in scoring.GENERIC_GENRES:
        return None, f"Qloo has no specific storefront category for '{query}', only the generic {name}."
    if not scoring.is_business_genre(name):
        return None, f"Qloo treats {name} as a taste cue or a non-storefront place, not a business to open here."
    known = next((genre for genre in ranked if genre["id"] == tag_id), None)
    return known or {"id": tag_id, "name": name, "rank": scoring.UNRANKED, "ref_rank": None}, None


def _match_quality(query: str, name: str) -> int:
    if query == name or query.replace(" ", "") == name.replace(" ", ""):  # "bookstore" is Qloo's "Book store"
        return 3
    query_words, name_words = set(query.split()), set(name.split())
    if query_words <= name_words:
        return 2  # a more specific category: "bakery" -> "vegan bakery"
    if name_words <= query_words:
        return 1  # a broader one: "natural wine bar" -> "wine bar"
    return 0


def _normalize_genre(text: str) -> str:
    text = " ".join(text.lower().replace("-", " ").split())
    text = text.removesuffix(" restaurants").removesuffix(" restaurant")
    if text.endswith("ies"):
        return text[:-3] + "y"
    if text.endswith(("ches", "shes", "sses", "xes")):
        return text[:-2]
    return text[:-1] if text.endswith("s") and not text.endswith("ss") else text


async def probe_genre(q: QlooClient, catchment: Catchment, genre: dict, table: list[dict]) -> dict:
    """Live evidence for one more genre, scored on the same supply baseline as the site's gap table."""
    row = await genre_evidence(q, catchment, genre)
    around_area = math.pi * around_radius(catchment) ** 2
    return scoring.score_gaps([row], catchment.area_m2, around_area, baseline_rows=table)[0]


async def fan_taste(q: QlooClient, lat: float, lon: float, tag_id: str, take: int = 15) -> dict:
    """Brands and artists that people who love a genre also love (Qloo cross-domain affinity, biased to the site).

    Mostly the category's audience at large rather than locals: seafood lovers rank much the same in Brooklyn and Cairo.
    """
    signal = {
        "signal.interests.tags": tag_id,
        "signal.location": point_wkt(lat, lon),
        "signal.location.radius": TASTE_M,
        "filter.popularity.min": 0.1,
        "take": take,
    }
    brands, artists = await asyncio.gather(
        q.insights({"filter.type": "urn:entity:brand", **signal}),
        q.insights({"filter.type": "urn:entity:artist", **signal}),
    )
    return {
        "brands": [
            scoring.entity_card(e) for e in scoring.entities(brands)
            if scoring.is_commercial_brand(e) and scoring.is_safe_name(e.get("name"))
        ][:10],
        "artists": [scoring.entity_card(e) for e in scoring.entities(artists) if scoring.is_safe_name(e.get("name"))][:10],
    }


async def _ranked(q: QlooClient, entity_type: str, lat: float, lon: float, radius: int, take: int = 30) -> list[dict]:
    return scoring.entities(await q.insights({
        "filter.type": entity_type,
        "filter.popularity.min": 0.1,
        "signal.location": point_wkt(lat, lon),
        "signal.location.radius": radius,
        "take": take,
    }))


async def local_taste(q: QlooClient, lat: float, lon: float) -> dict:
    """What the neighborhood loves and over-indexes on versus same-size areas around, across taste domains.

    Brands and artists keep their popular lists too (they show when Qloo ranks the categories' fans like everyone
    else); for films, shows and podcasts only the distinctive ones are kept: popular ones are popular everywhere.
    """
    refs = reference_points(lat, lon, TASTE_M, TASTE_REF_BEARINGS)
    kinds = list(TASTE_DOMAINS.values())
    lists = await asyncio.gather(*(
        _ranked(q, kind, r_lat, r_lon, TASTE_M) for kind in kinds for r_lat, r_lon in [(lat, lon), *refs]
    ))
    per_kind = len(refs) + 1
    taste: dict[str, list[dict]] = {}
    for index, domain in enumerate(TASTE_DOMAINS):
        local, *references = lists[index * per_kind:(index + 1) * per_kind]
        if domain == "brands":
            local = [e for e in local if scoring.is_commercial_brand(e)]
        if domain in ("brands", "artists"):
            taste[domain] = [scoring.entity_card(e) for e in local if scoring.is_safe_name(e.get("name"))][:12]
        taste[f"distinctive_{domain}"] = [scoring.entity_card(e) for e in scoring.distinctive_by_rank(local, references)]
    return taste


async def search_places(q: QlooClient, query: str, lat: float, lon: float, miles: int = 2, take: int = 8) -> list[dict]:
    """Places whose name matches, near a point. Qloo's search radius is in miles and results are ranked by relevance."""
    data = await q.search({
        "query": query.strip()[:80], "types": "urn:entity:place", "filter.location": f"{lat},{lon}",
        "filter.radius": miles, "take": take,
    })
    results = data.get("results")
    return [e for e in results if isinstance(e, dict) and e.get("entity_id")] if isinstance(results, list) else []


async def place_by_id(q: QlooClient, entity_id: str) -> dict | None:
    """The full record of a place.

    /entities returns a thin record (no keywords, reviews or Michelin), so the place is found through it and then read
    from insights within a few meters of its location, where Qloo returns everything it knows.
    """
    data = await q.entities({"entity_ids": entity_id})
    results = data.get("results")
    found = results if isinstance(results, list) else (results or {}).get("entities", []) if isinstance(results, dict) else []
    thin = next((e for e in found if scoring.item_id(e) == entity_id), None)
    location = scoring.place_location(thin) if thin else None
    if not location:
        return thin
    around = await places_in(q, circle_filter(*location, 60), take=20)
    return next((e for e in around if scoring.item_id(e) == entity_id), thin)


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
            "geohash": c["location"].get("geohash"),
            "affinity": round(c["query"].get("affinity_rank", c["query"].get("affinity", 0)), 3),
        }
        for c in cells
        if c.get("location") and c.get("query")
    ]
