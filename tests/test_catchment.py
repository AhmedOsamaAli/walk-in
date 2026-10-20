import math

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
