import asyncio
import json
import math

import httpx

from app import catchment as walk


def test_circle_ring_area_matches_pi_r_squared():
    ring = walk.circle_ring(40.0, -73.0, 800, vertices=72)
    area = walk.ring_area_m2(ring, 40.0)
    expected = math.pi * 800**2
    assert abs(area - expected) / expected < 0.01


def test_point_in_ring():
    ring = walk.circle_ring(40.0, -73.0, 800)
    assert walk.point_in_ring(40.0, -73.0, ring)
    assert not walk.point_in_ring(40.02, -73.0, ring)


def test_parse_isochrone_keeps_largest_ring_and_closes_it():
    data = {"features": [{"geometry": {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [1, 0], [1, 1]]],
        [[[0, 0], [2, 0], [2, 2], [0, 2]]],
    ]}}]}
    ring = walk.parse_isochrone(data)
    assert ring[0] == ring[-1]
    assert len(ring) == 5


def test_parse_isochrone_rejects_empty_payloads():
    assert walk.parse_isochrone({}) is None
    assert walk.parse_isochrone({"features": [{"geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]}}]}) is None


def test_circle_catchment_shape():
    catchment = walk.circle_catchment(40.0, -73.0, 10)
    assert catchment.source == "circle"
    assert catchment.wkt.startswith("POLYGON((")
    assert 780 <= catchment.radius_m <= 800
    public = catchment.public()
    assert public["minutes"] == 10
    assert public["ring"][0] == [catchment.ring[0][1], catchment.ring[0][0]]
    assert catchment.contains(40.0, -73.0)


def contour(minutes: int, radius_m: float) -> dict:
    ring = walk.circle_ring(40.0, -73.0, radius_m)
    return {"properties": {"contour": float(minutes)}, "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring]]}}


def service(tmp_path, reply: dict | None, seen: list | None = None) -> walk.CatchmentService:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json=reply) if reply is not None else httpx.Response(503)

    svc = walk.CatchmentService(tmp_path)
    svc._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return svc


def test_one_request_traces_the_walk_and_the_longer_walk_supply_is_compared_with(tmp_path):
    seen: list = []
    # Valhalla sends the larger contour first.
    svc = service(tmp_path, {"features": [contour(20, 1300), contour(10, 700)]}, seen)
    got = asyncio.run(svc.walk(40.0, -73.0, 10))
    assert [c["time"] for c in seen[0]["contours"]] == [10, 20]
    assert got.source == "street network" and 690 <= got.radius_m <= 710
    assert math.isclose(got.around_area_m2, math.pi * 1300 ** 2, rel_tol=0.02) and got.around_wkt.startswith("POLYGON((")
    # Both come back from the cache, without another request.
    again = asyncio.run(service(tmp_path, None).walk(40.0, -73.0, 10))
    assert again.ring == got.ring and again.around == got.around


def test_a_walk_cached_before_the_around_area_is_traced_again(tmp_path):
    old = walk.circle_ring(40.0, -73.0, 700)
    key = __import__("hashlib").sha1(b"40.00000,-73.00000,10").hexdigest()
    (tmp_path / f"walk-{key}.json").write_text(json.dumps({"source": "street network", "ring": old}), encoding="utf-8")
    got = asyncio.run(service(tmp_path, {"features": [contour(20, 1300), contour(10, 700)]}).walk(40.0, -73.0, 10))
    assert got.around is not None


def test_without_routing_the_walk_is_a_circle_and_nothing_is_cached(tmp_path):
    got = asyncio.run(service(tmp_path, None).walk(40.0, -73.0, 10))
    assert got.source == "circle" and got.around is None and not list(tmp_path.iterdir())
    # A walk without a believable longer walk keeps the walk, and is cached that way: supply then uses the circle.
    small = asyncio.run(service(tmp_path, {"features": [contour(20, 100), contour(10, 700)]}).walk(40.0, -73.0, 10))
    assert small.source == "street network" and small.around is None
    assert asyncio.run(service(tmp_path, None).walk(40.0, -73.0, 10)).ring == small.ring


def test_a_walk_cached_before_the_around_area_survives_a_routing_failure(tmp_path):
    old = walk.circle_ring(40.0, -73.0, 650)
    key = __import__("hashlib").sha1(b"40.00000,-73.00000,10").hexdigest()
    (tmp_path / f"walk-{key}.json").write_text(json.dumps({"source": "street network", "ring": old}), encoding="utf-8")
    got = asyncio.run(service(tmp_path, None).walk(40.0, -73.0, 10))
    assert got.source == "street network" and got.ring == [tuple(p) for p in old] and got.around is None


def test_parse_isochrone_picks_a_contour_by_its_minutes():
    data = {"features": [contour(20, 1300), contour(10, 700)]}
    ten, twenty = walk.parse_isochrone(data, 10), walk.parse_isochrone(data, 20)
    assert walk.ring_area_m2(ten, 40.0) < walk.ring_area_m2(twenty, 40.0)
    assert walk.parse_isochrone(data, 15) is None
