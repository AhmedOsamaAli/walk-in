"""Walking catchments: the area reachable on foot over the street network, with a circle fallback.

Isochrones come from the public Valhalla instance run by FOSSGIS (OpenStreetMap data). Results are
cached on disk; if the service fails the catchment falls back to a circle of minutes x 80 m.
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
ALLOWED_MINUTES = (5, 10, 15)
_M_PER_DEG = 111_320.0


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


@dataclass
class Catchment:
    lat: float
    lon: float
    minutes: int
    source: str
    ring: list[tuple[float, float]]

    @property
    def area_m2(self) -> float:
        return ring_area_m2(self.ring, self.lat)

    @property
    def radius_m(self) -> float:
        """Radius of a circle with the same area."""
        return math.sqrt(self.area_m2 / math.pi)

    @property
    def wkt(self) -> str:
        return "POLYGON((" + ", ".join(f"{lon} {lat}" for lon, lat in self.ring) + "))"

    def contains(self, lat: float, lon: float) -> bool:
        return point_in_ring(lat, lon, self.ring)

    def public(self) -> dict:
        return {
            "minutes": self.minutes,
            "source": self.source,
            "ring": [[lat, lon] for lon, lat in self.ring],
            "area_km2": round(self.area_m2 / 1e6, 3),
            "radius_m": round(self.radius_m),
        }


def circle_catchment(lat: float, lon: float, minutes: int) -> Catchment:
    return Catchment(lat, lon, minutes, "circle", circle_ring(lat, lon, minutes * WALK_M_PER_MIN))


def parse_isochrone(data: dict) -> list[tuple[float, float]] | None:
    features = data.get("features") or []
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


class CatchmentService:
    def __init__(self, cache_dir: Path, url: str = VALHALLA_URL, timeout: float = 12.0) -> None:
        self._cache_dir = cache_dir
        self._url = url
        self._http = httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "BlankSpace/0.2 (Qloo Agentic Hackathon)"})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def walk(self, lat: float, lon: float, minutes: int = 10) -> Catchment:
        minutes = minutes if minutes in ALLOWED_MINUTES else 10
        key = hashlib.sha1(f"{lat:.5f},{lon:.5f},{minutes}".encode()).hexdigest()
        cache_file = self._cache_dir / f"walk-{key}.json"
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            return Catchment(lat, lon, minutes, cached["source"], [tuple(p) for p in cached["ring"]])
        catchment = await self._fetch(lat, lon, minutes)
        if catchment.source != "circle":
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"source": catchment.source, "ring": catchment.ring}), encoding="utf-8")
        return catchment

    async def _fetch(self, lat: float, lon: float, minutes: int) -> Catchment:
        query = {
            "locations": [{"lat": lat, "lon": lon}],
            "costing": "pedestrian",
            "contours": [{"time": minutes}],
            "polygons": True,
            "denoise": 0.5,
            "generalize": 20,
        }
        try:
            response = await self._http.post(self._url, json=query)
            response.raise_for_status()
            ring = parse_isochrone(response.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            ring = None
        if ring:
            catchment = Catchment(lat, lon, minutes, "street network", ring)
            expected = math.pi * (minutes * WALK_M_PER_MIN) ** 2
            # Reject degenerate shapes (snapped to a far road, or nearly empty).
            if 0.05 * expected <= catchment.area_m2 <= 1.5 * expected:
                return catchment
        return circle_catchment(lat, lon, minutes)
