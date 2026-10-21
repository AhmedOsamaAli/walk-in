"""Synthetic stand-ins for external services, used by the end-to-end tests.

The fake Qloo world is invented (no real Qloo data may be committed). It is shaped so the expected outcome
is known: Seafood is loved more here than around, under-supplied, and its local favorites lie outside the
walk; Yoga is barely known locally (thin); Gift shop favorites are hotels (atypical). Ramen and Board Game
Cafe sit outside the gap table for the agent's live tests, and Seafood's local fans share taste with the area.
"""
from __future__ import annotations

import math
import re

from app.catchment import circle_catchment
from app.geo import distance_m

SITE = (40.0, -73.0)

GENRES = {
    "Seafood": "urn:tag:genre:place:test_seafood",
    "Brunch": "urn:tag:genre:place:test_brunch",
    "Wine Bar": "urn:tag:genre:place:test_wine_bar",
    "Coffee shop": "urn:tag:genre:place:test_coffee_shop",
    "Japanese": "urn:tag:genre:place:test_japanese",
    "Bakery": "urn:tag:genre:place:test_bakery",
    "Gift shop": "urn:tag:genre:place:test_gift_shop",
    "Yoga studio": "urn:tag:genre:place:test_yoga_studio",
    # Outside the 8-row gap table: Ramen is ranked 9th locally, Board Game Cafe only exists in tag search.
    "Ramen": "urn:tag:genre:place:test_ramen",
    "Board Game Cafe": "urn:tag:genre:place:test_board_game_cafe",
}
GENRE_BY_ID = {tag: name for name, tag in GENRES.items()}
TAG_CATALOG = list(GENRES) + ["Art museum"]

LOCAL_RANKING = ["Restaurant", "Seafood", "Brunch", "Wine Bar", "Art museum", "Coffee shop", "Japanese", "Bakery",
                 "Gift shop", "Yoga studio", "Ramen"]
REFERENCE_RANKING = ["Brunch", "Coffee shop", "Wine Bar", "Bakery", "Japanese", "Gift shop", "Yoga studio", "Seafood"]
NEARBY = {"Seafood": 1, "Brunch": 12, "Wine Bar": 9, "Coffee shop": 14, "Japanese": 5, "Bakery": 4, "Gift shop": 2,
          "Yoga studio": 0, "Ramen": 0, "Board Game Cafe": 0}
AROUND = {"Seafood": 12, "Brunch": 30, "Wine Bar": 22, "Coffee shop": 34, "Japanese": 13, "Bakery": 10,
          "Gift shop": 5, "Yoga studio": 1, "Ramen": 9, "Board Game Cafe": 2}
# Every synthetic place keeps these hours: 11 am to 10 pm, until 11:30 pm on Fridays and Saturdays.
WEEK_HOURS = {
    day: [{"opens": "T11:00:00", "closes": "T23:30:00" if day in ("friday", "saturday") else "T22:00:00", "closed": False}]
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
}
# What people near the site who love a genre also love; Seafood fans share two names with the area's signature taste.
FAN_TASTE = {"Seafood": {"brands": ["Riverside Cider Co", "Tide Magazine"], "artists": ["Sea Shanty Crew", "Local Jazz Trio"]}}
DEFAULT_FANS = {"brands": ["Global Coffee"], "artists": ["Global Pop Star"]}
SEAFOOD_LOCAL_FAVORITES = ["Harbor Oyster Bar", "Dockside Crab", "Saltwater Kitchen", "Pier Nine Fish", "Tidal Grill"]
WINE_LOCAL_FAVORITES = ["Corner Cellar", "Vine & Barrel", "The Cork Room", "Little Pour"]
LOCAL_BRANDS = [
    "Global Coffee", "Global Sneakers", "Block News", "Local Sports Team", "Riverside Cider Co", "Neighborhood Bikes",
    "Civic Advocacy Org",
]
BRAND_TYPES = {
    "Block News": "Media Brand", "Local Sports Team": "Entertainment Brand", "Riverside Cider Co": "Product Brand",
    "Neighborhood Bikes": "Retail Brand", "Civic Advocacy Org": "Nonprofit Brand", "Tide Magazine": "Media Brand",
}
REFERENCE_BRANDS = ["Global Coffee", "Global Sneakers"] + [f"Elsewhere Brand {i}" for i in range(10)]
LOCAL_ARTISTS = ["Global Pop Star", "Block Party Band", "Local Jazz Trio"]
REFERENCE_ARTISTS = ["Global Pop Star"] + [f"Elsewhere Artist {i}" for i in range(10)]


def offset(distance: float, bearing: float) -> tuple[float, float]:
    lat, lon = SITE
    return (lat + distance * math.cos(math.radians(bearing)) / 111_320,
            lon + distance * math.sin(math.radians(bearing)) / (111_320 * math.cos(math.radians(lat))))


def parse_point(wkt: str) -> tuple[float, float] | None:
    match = re.match(r"POINT\(([-\d.]+) ([-\d.]+)\)", wkt or "")
    return (float(match.group(2)), float(match.group(1))) if match else None


def at_site(wkt: str) -> bool:
    point = parse_point(wkt)
    return bool(point) and distance_m(*point, *SITE) < 50


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def place(name: str, genre: str, lat: float, lon: float, index: int = 0, genre_tag: tuple[str, str] | None = None) -> dict:
    tag_id, tag_name = genre_tag or (GENRES.get(genre, f"urn:tag:genre:place:test_{slug(genre)}"), genre)
    return {
        "entity_id": f"place-{slug(name)}",
        "name": name,
        "popularity": round(0.9 - index * 0.01, 3),
        "location": {"lat": lat, "lon": lon},
        "tags": [
            {"id": tag_id, "name": tag_name, "type": "urn:tag:genre:place"},
            {"id": "urn:tag:decor:qloo:industrial", "name": "Industrial chic", "type": "urn:tag:decor:qloo"},
            {"id": "urn:tag:ambience:qloo:lively", "name": "Lively", "type": "urn:tag:ambience:qloo"},
            {"id": "urn:tag:menu_highlight:qloo:house", "name": f"House {genre.lower()} special", "type": "urn:tag:menu_highlight:qloo"},
        ],
        "properties": {
            "address": f"{index + 1} Test Street",
            "business_rating": 4.0 + (index % 9) / 10,
            "price_level": 1 + index % 3,
            "keywords": [{"name": "outdoor seating", "count": 20 + index}, {"name": "long wait" if index % 4 == 0 else "friendly staff", "count": 5}],
            "hours": WEEK_HOURS,
        },
        # Every fifth place has a long review history, so blocks and favorites have established places.
        "external": {"tripadvisor": [{"id": f"d{index}", "rating": 4.5, "rating_count": 1000 - index if index % 5 == 0 else 30}]},
        "query": {"affinity": 0.9},
    }


def entity(name: str, kind: str, index: int, brand_type: str = "Corporate Brand") -> dict:
    tags = [{"type": "urn:tag:brand_type:qloo", "name": brand_type}] if kind == "brand" else []
    return {"entity_id": f"{kind}-{slug(name)}", "name": name, "popularity": 0.8, "tags": tags, "properties": {}}


class FakeQloo:
    configured = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0
        self.cache_hits = 0
        self.requests: list[dict] = []

    async def aclose(self) -> None:
        pass

    async def search(self, params: dict) -> dict:
        return {"results": []}

    async def tags(self, params: dict) -> dict:
        from app.qloo import QlooError

        self.calls += 1
        self.requests.append({"path": "/v2/tags", **params})
        if self.fail:
            raise QlooError("Qloo returned HTTP 401: invalid key")
        query = params.get("filter.query", "").lower()
        names = [name for name in TAG_CATALOG if query and (query in name.lower() or name.lower() in query)]
        return {"results": {"tags": [
            {"id": GENRES.get(name, f"urn:tag:genre:place:test_{slug(name)}"), "name": name, "type": "urn:tag:genre:place"}
            for name in names
        ]}}

    async def insights(self, params: dict) -> dict:
        from app.qloo import QlooError

        self.calls += 1
        self.requests.append(params)
        if self.fail:
            raise QlooError("Qloo returned HTTP 401: invalid key")
        kind = params["filter.type"]
        if kind == "urn:tag":
            return self._genre_ranking(params)
        if kind == "urn:entity:place":
            return self._places(params)
        if kind in ("urn:entity:brand", "urn:entity:artist") and "signal.interests.tags" in params:
            fans = FAN_TASTE.get(GENRE_BY_ID.get(params["signal.interests.tags"], ""), DEFAULT_FANS)
            brand = kind == "urn:entity:brand"
            return {"results": {"entities": [
                entity(n, "brand" if brand else "artist", i, BRAND_TYPES.get(n, "Corporate Brand"))
                for i, n in enumerate(fans["brands" if brand else "artists"])
            ]}}
        if kind == "urn:entity:brand":
            names = LOCAL_BRANDS if at_site(params.get("signal.location", "")) else REFERENCE_BRANDS
            return {"results": {"entities": [
                entity(n, "brand", i, BRAND_TYPES.get(n, "Corporate Brand")) for i, n in enumerate(names)
            ]}}
        if kind == "urn:entity:artist":
            names = LOCAL_ARTISTS if at_site(params.get("signal.location", "")) else REFERENCE_ARTISTS
            return {"results": {"entities": [entity(n, "artist", i) for i, n in enumerate(names)]}}
        if kind == "urn:heatmap":
            cells = []
            for i in range(30):
                lat, lon = offset(150 * (i % 6), 60 * (i // 6))
                cells.append({"location": {"latitude": lat, "longitude": lon, "geohash": "dr5ru7k"},
                              "query": {"affinity": 0.95 - i * 0.02, "affinity_rank": 0.95 - i * 0.02, "popularity": 0.5}})
            return {"results": {"heatmap": cells}}
        return {"results": {}}

    def _genre_ranking(self, params: dict) -> dict:
        signal = params.get("signal.location", "")
        names = LOCAL_RANKING if signal.startswith("POLYGON") else REFERENCE_RANKING
        tags = []
        for name in names:
            tag_id = GENRES.get(name, f"urn:tag:genre:place:test_{slug(name)}")
            tags.append({"tag_id": tag_id, "name": name, "subtype": "urn:tag:genre:place"})
        return {"results": {"tags": tags}}

    def _places(self, params: dict) -> dict:
        genre = GENRE_BY_ID.get(params.get("filter.tags", ""))
        location = params.get("filter.location", "")
        if not genre:
            return {"results": {"entities": self._block(params)}}
        if "signal.location" in params:
            city = params.get("signal.location.radius", 0) >= 10_000
            return {"results": {"entities": self._favorites(genre, city)}}
        if location.startswith("POLYGON"):
            count = NEARBY[genre]
            return {"results": {"entities": [
                place(f"{genre} Nearby {i}", genre, *offset(100 + 30 * i, 37 * i), i) for i in range(count)
            ]}}
        count = AROUND[genre]
        return {"results": {"entities": [
            place(f"{genre} Around {i}", genre, *offset(300 + 40 * i, 23 * i), i) for i in range(count)
        ]}}

    def _block(self, params: dict) -> list[dict]:
        if params.get("offset"):
            return []
        cycle = ["Brunch", "Wine Bar", "Coffee shop", "Japanese", "Bakery"]
        return [place(f"Block Place {i}", cycle[i % len(cycle)], *offset(60 + 10 * i, 47 * i), i) for i in range(30)]

    def _favorites(self, genre: str, city: bool) -> list[dict]:
        famous = [place(f"Famous {genre} {i}", genre, *offset(6000 + 200 * i, 15 * i), i) for i in range(20)]
        if city:
            return famous
        if genre == "Seafood":
            own = [place(n, genre, *offset(2500 + 400 * i, 90 + 20 * i), i) for i, n in enumerate(SEAFOOD_LOCAL_FAVORITES)]
            return famous[:5] + own + famous[5:15]
        if genre == "Wine Bar":
            own = [place(n, genre, *offset(150 + 50 * i, 200 + 30 * i), i) for i, n in enumerate(WINE_LOCAL_FAVORITES)]
            return famous[:5] + own + famous[5:16]
        if genre == "Gift shop":
            hotels = [place(f"Grand Hotel {i}", genre, *offset(3000, 30 * i), i, ("urn:tag:genre:place:hotel", "Hotel"))
                      for i in range(10)]
            return hotels + famous[:10]
        return famous[:18] + [place(f"{genre} Local Gem {i}", genre, *offset(500, 90 * i), i) for i in range(2)]


class FakeWalker:
    async def walk(self, lat: float, lon: float, minutes: int = 10):
        return circle_catchment(lat, lon, minutes)

    async def aclose(self) -> None:
        pass


class StubGeocoder:
    async def search(self, query: str) -> list[dict]:
        return [{"label": f"{query}, Testville", "lat": SITE[0], "lon": SITE[1]}]

    async def aclose(self) -> None:
        pass


class FakeImages:
    """Stands in for an image model; records every prompt it is asked to render."""

    provider = "fake"
    TINY_PNG = "data:image/png;base64,iVBORw0KGgo="

    def __init__(self, enabled: bool = True, fail: bool = False) -> None:
        self.enabled = enabled
        self.fail = fail
        self.error: Exception | None = None
        self.calls: list[tuple[str, str]] = []

    @property
    def model(self) -> str | None:
        return "fake-image-model" if self.enabled else None

    async def generate(self, prompt: str, aspect: str = "16:9") -> str | None:
        self.calls.append((prompt, aspect))
        if self.error:
            raise self.error
        if self.fail:
            raise RuntimeError("the image model is down")
        return self.TINY_PNG

    async def render(self, prompt: str, aspect: str = "16:9") -> tuple[str | None, str | None]:
        return await self.generate(prompt, aspect), self.model

    async def aclose(self) -> None:
        pass
