"""Catchments: the area reachable on foot or by car over the street network, or within a road distance, with a circle
fallback.

Isochrones come from the public Valhalla instance run by FOSSGIS (OpenStreetMap data). One request returns two contours:
the area itself, and the area a trip twice as long (or far) reaches, which the gap table compares supply with ("around").
Both follow the streets, so a river, a park or the sea is no part of either unless a bridge or a path crosses it. That
instance answers trips of at most 60 minutes and 100 km, which is why areas stop there; when twice as long would pass
that, there is no around outline and the gap table compares supply with a circle instead. Results are cached on disk;
if the service fails the area falls back to a circle (80 m per minute on foot, 400 m per minute by car, 0.7 of a road
distance), and the report says so.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import httpx

VALHALLA_URL = "https://valhalla1.openstreetmap.de/isochrone"
WALK_M_PER_MIN = 80
DRIVE_M_PER_MIN = 400  # circle fallback for a drive: 24 km/h, city traffic and lights
ROAD_FACTOR = 0.7  # circle fallback for a road distance: roads wind, so a straight line reaches less far
ALLOWED_MINUTES = (5, 10, 15)  # the walks offered before drives and distances; kept for old callers
TRAVEL_MODES = ("walk", "drive", "distance")
MIN_MINUTES, MAX_MINUTES = 5, 60  # the public Valhalla instance refuses time contours over 60 minutes
MIN_KM, MAX_KM = 1.0, 100.0  # and distance contours over 100 km
AROUND_FACTOR = 2  # the area supply is compared with: a trip this many times as long, about twice the area's radius
QLOO_RING_POINTS = 180  # Qloo reads an area from the URL and refuses long ones (HTTP 414), so outlines are simplified
_M_PER_DEG = 111_320.0


def _km_text(km: float) -> str:
    return f"{km:g}"


@dataclass(frozen=True)
class Reach:
    """How far the area reaches: a walk or a drive of `minutes`, or a road distance of `km`."""

    travel: str = "walk"
    minutes: int = 10
    km: float | None = None

    @property
    def label(self) -> str:
        """The area in a sentence: 'inside the 10-minute walk', 'within a 30-minute drive', 'within a 25 km drive'."""
        if self.travel == "distance":
            return f"{_km_text(self.km or 0)} km drive"
        return f"{self.minutes}-minute {'drive' if self.travel == 'drive' else 'walk'}"

    @property
    def short(self) -> str:
        if self.travel == "distance":
            return self.label
        return f"{self.minutes}-min {'drive' if self.travel == 'drive' else 'walk'}"

    @property
    def amount(self) -> float:
        return float(self.km or 0) if self.travel == "distance" else float(self.minutes)

    @property
    def around(self) -> Reach | None:
        """The trip twice as long or far, or None past what the router answers."""
        if self.travel == "distance":
            far = min(AROUND_FACTOR * (self.km or 0), MAX_KM)
            return Reach("distance", self.minutes, far) if far > (self.km or 0) else None
        longer = min(AROUND_FACTOR * self.minutes, MAX_MINUTES)
        return Reach(self.travel, longer) if longer > self.minutes else None

    @property
    def costing(self) -> str:
        return "pedestrian" if self.travel == "walk" else "auto"

    @property
    def contour(self) -> dict:
        return {"distance": self.km} if self.travel == "distance" else {"time": self.minutes}

    @property
    def fallback_radius_m(self) -> float:
        if self.travel == "distance":
            return (self.km or 0) * 1000 * ROAD_FACTOR
        return self.minutes * (DRIVE_M_PER_MIN if self.travel == "drive" else WALK_M_PER_MIN)

    @property
    def generalize_m(self) -> int:
        """How much Valhalla smooths the outline: a walk keeps its corners, a big drive needs no 20 m detail."""
        if self.travel == "walk":
            return 20
        return int(min(300, max(40, 3 * self.amount)))

    def public(self) -> dict:
        return {"travel": self.travel, "minutes": self.minutes, "km": self.km, "label": self.label, "short": self.short}


def make_reach(travel: str = "walk", minutes: int | None = 10, km: float | None = None) -> Reach:
    """The area the owner asked for, checked against what the router answers; ValueError says what is wrong."""
    if travel not in TRAVEL_MODES:
        raise ValueError("The area must be a walk, a drive or a road distance")
    if travel == "distance":
        if km is None or not (MIN_KM <= km <= MAX_KM):
            raise ValueError("A road distance must be 1 to 100 km")
        return Reach("distance", 10, round(float(km), 1))
    if minutes is None or not (MIN_MINUTES <= minutes <= MAX_MINUTES):
        raise ValueError(f"{'Drive' if travel == 'drive' else 'Walk'} time must be 5 to 60 minutes")
    return Reach(travel, int(minutes))


def area_text(area: str | int) -> str:
    """The area in a sentence: a label as given ('30-minute drive'), or old callers' walk minutes ('10-minute walk')."""
    return f"{area}-minute walk" if isinstance(area, int) else area


def ring_area_m2(ring: list[tuple[float, float]], lat0: float) -> float:
    """Planar area of a closed (lon, lat) ring, using a local equirectangular projection."""
    kx = _M_PER_DEG * math.cos(math.radians(lat0))
    pts = [(lon * kx, lat * _M_PER_DEG) for lon, lat in ring]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1], strict=True))) / 2


def point_in_ring(lat: float, lon: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1], strict=True):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def circle_ring(lat: float, lon: float, radius_m: float, vertices: int = 40) -> list[tuple[float, float]]:
    dlat = radius_m / _M_PER_DEG
    dlon = radius_m / (_M_PER_DEG * math.cos(math.radians(lat)))
    ring = [
        (round(lon + dlon * math.cos(2 * math.pi * i / vertices), 6), round(lat + dlat * math.sin(2 * math.pi * i / vertices), 6))
        for i in range(vertices)
    ]
    return ring + [ring[0]]


def simplify_ring(ring: list[tuple[float, float]], max_points: int = QLOO_RING_POINTS) -> list[tuple[float, float]]:
    """The outline with at most `max_points` points (Douglas-Peucker, coarser until it fits); short rings as they are."""
    if len(ring) <= max_points:
        return ring
    tolerance = 1e-5
    while True:
        kept = _douglas_peucker(ring, tolerance)
        if len(kept) <= max_points:
            return kept if kept[0] == kept[-1] else kept + [kept[0]]
        tolerance *= 1.6


def _douglas_peucker(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy)
        worst, index = 0.0, None
        for i in range(first + 1, last):
            px, py = points[i]
            d = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / norm if norm else math.hypot(px - x1, py - y1)
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep, strict=True) if k]


@dataclass
class Catchment:
    lat: float
    lon: float
    minutes: int
    source: str
    ring: list[tuple[float, float]]
    # The area a trip of AROUND_FACTOR times the minutes (or km) reaches over the streets, as (lon, lat); None when
    # routing failed or the router cannot go that far, and the gap table then compares supply with a circle twice the
    # area's radius.
    around: list[tuple[float, float]] | None = None
    travel: str = "walk"
    km: float | None = None

    @property
    def reach(self) -> Reach:
        return Reach(self.travel, self.minutes, self.km)

    @property
    def label(self) -> str:
        return self.reach.label

    @property
    def around_label(self) -> str:
        """The trip supply is compared with: '20-minute walk'. Without its outline (routing failed, or past the
        router's reach) supply is compared with a circle, named for what it is."""
        around = self.reach.around
        return around.label if around and self.around else f"area twice as wide as the {self.label}"

    @property
    def area_m2(self) -> float:
        return ring_area_m2(self.ring, self.lat)

    @property
    def radius_m(self) -> float:
        """Radius of a circle with the same area."""
        return math.sqrt(self.area_m2 / math.pi)

    @property
    def wkt(self) -> str:
        return ring_wkt(simplify_ring(self.ring))

    @property
    def around_minutes(self) -> int:
        return min(AROUND_FACTOR * self.minutes, MAX_MINUTES)

    @property
    def around_area_m2(self) -> float | None:
        return ring_area_m2(self.around, self.lat) if self.around else None

    @property
    def around_wkt(self) -> str | None:
        return ring_wkt(simplify_ring(self.around)) if self.around else None

    def contains(self, lat: float, lon: float) -> bool:
        return point_in_ring(lat, lon, self.ring)

    def public(self) -> dict:
        return {
            "minutes": self.minutes,
            "source": self.source,
            "ring": [[lat, lon] for lon, lat in self.ring],
            "area_km2": round(self.area_m2 / 1e6, 3),
            "radius_m": round(self.radius_m),
            **{key: value for key, value in self.reach.public().items() if key != "minutes"},
        }


def ring_wkt(ring: list[tuple[float, float]]) -> str:
    return "POLYGON((" + ", ".join(f"{lon} {lat}" for lon, lat in ring) + "))"


def circle_catchment(lat: float, lon: float, minutes: int, reach: Reach | None = None) -> Catchment:
    reach = reach or Reach("walk", minutes)
    return Catchment(
        lat, lon, reach.minutes, "circle", circle_ring(lat, lon, reach.fallback_radius_m), travel=reach.travel, km=reach.km,
    )


def parse_isochrone(data: dict, minutes: float | None = None) -> list[tuple[float, float]] | None:
    """The outline of one contour (`minutes`; without it, the first feature), as a closed (lon, lat) ring."""
    features = data.get("features") or []
    if minutes is not None:
        features = [f for f in features if _contour(f) == float(minutes)]
    if not features:
        return None
    geometry = features[0].get("geometry") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "MultiPolygon":
        # Keep the largest outer ring.
        rings = [polygon[0] for polygon in coords if polygon]
        coords = [max(rings, key=len)] if rings else []
    if not coords or len(coords[0]) < 4:
        return None
    ring = [(round(float(p[0]), 6), round(float(p[1]), 6)) for p in coords[0]]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _contour(feature: dict) -> float | None:
    try:
        return float((feature.get("properties") or {}).get("contour"))
    except (TypeError, ValueError):
        return None


def plausible(ring: list[tuple[float, float]] | None, lat: float, minutes: int, reach: Reach | None = None) -> bool:
    """Whether an outline has a believable size: not snapped to a far road, not nearly empty."""
    if not ring:
        return False
    reach = reach or Reach("walk", minutes)
    area = ring_area_m2(ring, lat)
    if reach.travel == "walk":
        expected = math.pi * (reach.minutes * WALK_M_PER_MIN) ** 2
        return 0.05 * expected <= area <= 1.5 * expected
    if reach.travel == "drive":
        expected = math.pi * (reach.minutes * 1000) ** 2  # 60 km/h in every direction
        return 0.002 * expected <= area <= 4 * expected
    expected = math.pi * ((reach.km or 0) * 1000) ** 2  # no road reaches farther than the distance itself
    return 0.002 * expected <= area <= 1.05 * expected


class CatchmentService:
    def __init__(self, cache_dir: Path, url: str = VALHALLA_URL, timeout: float = 12.0) -> None:
        self._cache_dir = cache_dir
        self._url = url
        self._timeout = timeout
        self._http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "Walk-in/0.2 (Qloo Agentic Hackathon)"})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def walk(self, lat: float, lon: float, minutes: int = 10) -> Catchment:
        minutes = minutes if MIN_MINUTES <= minutes <= MAX_MINUTES else 10
        return await self.area(lat, lon, Reach("walk", minutes))

    async def area(self, lat: float, lon: float, reach: Reach) -> Catchment:
        key = hashlib.sha1(self._key(lat, lon, reach).encode()).hexdigest()
        cache_file = self._cache_dir / f"walk-{key}.json"
        cached = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else None
        if cached and "around" in cached:
            around = [tuple(p) for p in cached["around"]] if cached["around"] else None
            return Catchment(
                lat, lon, reach.minutes, cached["source"], [tuple(p) for p in cached["ring"]], around,
                travel=reach.travel, km=reach.km,
            )
        catchment = await self._fetch(lat, lon, reach)
        if catchment.source == "circle":
            # An outline cached before the around area existed beats a circle when routing fails now.
            if cached:
                return Catchment(
                    lat, lon, reach.minutes, cached["source"], [tuple(p) for p in cached["ring"]],
                    travel=reach.travel, km=reach.km,
                )
            return catchment
        # Both outlines come from one answer, so a longer trip that was not believable will not be next time either.
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({"source": catchment.source, "ring": catchment.ring, "around": catchment.around}),
            encoding="utf-8",
        )
        return catchment

    @staticmethod
    def _key(lat: float, lon: float, reach: Reach) -> str:
        if reach.travel == "walk":
            return f"{lat:.5f},{lon:.5f},{reach.minutes}"  # the key walks were cached under before drives existed
        return f"{lat:.5f},{lon:.5f},{reach.travel},{reach.amount:g}"

    async def _fetch(self, lat: float, lon: float, reach: Reach) -> Catchment:
        longer = reach.around
        query = {
            "locations": [{"lat": lat, "lon": lon}],
            "costing": reach.costing,
            "contours": [reach.contour] + ([longer.contour] if longer else []),
            "polygons": True,
            "denoise": 0.5,
            "generalize": reach.generalize_m,
        }
        timeout = self._timeout if reach.travel == "walk" else max(self._timeout, 30.0)  # big drives take seconds
        try:
            response = await self._http.post(self._url, json=query, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            ring = parse_isochrone(data, reach.amount)
            around = parse_isochrone(data, longer.amount) if longer else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            ring, around = None, None
        if plausible(ring, lat, reach.minutes, reach):
            if not (longer and plausible(around, lat, longer.minutes, longer)):
                around = None
            return Catchment(lat, lon, reach.minutes, "street network", ring, around, travel=reach.travel, km=reach.km)
        return circle_catchment(lat, lon, reach.minutes, reach)
