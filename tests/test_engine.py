"""The engine's place queries: paging through Qloo's 50-result pages, leaving out places Qloo marks closed, comparison
areas on land and supply counted where people can walk."""
import asyncio
import math

from app import engine
from app.catchment import Catchment, circle_catchment, circle_ring
from app.geo import point_wkt


def place(index: int, closed: bool = False) -> dict:
    return {"entity_id": f"p{index}", "name": f"Place {index}", "properties": {"is_closed": closed}}


class PagedQloo:
    """Answers place queries from a fixed list, 50 at a time, like Qloo's insights."""

    def __init__(self, places: list[dict]) -> None:
        self.places = places
        self.offsets: list[int] = []

    async def insights(self, params: dict) -> dict:
        offset = params.get("offset", 0)
        self.offsets.append(offset)
        return {"results": {"entities": self.places[offset:offset + params["take"]]}}


def test_closed_places_are_left_out_after_paging_so_paging_still_reaches_every_page():
    # The first page is full but holds a closed place; dropping it before paging would stop at one page.
    places = [place(i, closed=i == 3) for i in range(70)]
    q = PagedQloo(places)
    found = asyncio.run(engine.places_upto(q, {"filter.location": "x"}, "urn:tag:genre:place:bar", limit=100))
    assert q.offsets == [0, 50]
    assert len(found) == 69 and "p3" not in {p["entity_id"] for p in found}


def test_a_single_page_query_drops_closed_places_unless_asked_to_keep_them():
    q = PagedQloo([place(1), place(2, closed=True)])
    assert [p["entity_id"] for p in asyncio.run(engine.places_in(q, {}))] == ["p1"]
    assert [p["entity_id"] for p in asyncio.run(engine.places_in(q, {}, include_closed=True))] == ["p1", "p2"]


def test_favorites_located_far_outside_the_search_area_are_dropped():
    # Zamalek's search area is 15 km; a place placed in Austin, Texas is a data error, not a trip people make.
    here = {"entity_id": "a", "name": "Near", "location": {"lat": 30.07, "lon": 31.23}}
    austin = {"entity_id": "b", "name": "Far", "location": {"lat": 30.2622, "lon": -97.7247}}
    unknown = {"entity_id": "c", "name": "Nowhere"}
    kept = engine.near([here, austin, unknown], 30.0626, 31.2197)
    assert [p["entity_id"] for p in kept] == ["a", "c"]


class Shoreline:
    """A Qloo whose places all stand east of a longitude: everything west of it is open water."""

    def __init__(self, shore_lon: float) -> None:
        self.shore_lon = shore_lon
        self.asked: list[tuple[float, float]] = []

    async def insights(self, params: dict) -> dict:
        lon, lat = (float(v) for v in params["filter.location"].removeprefix("POINT(").removesuffix(")").split())
        self.asked.append((lat, lon))
        found = [] if lon < self.shore_lon else [place(i) for i in range(params["take"])]
        return {"results": {"entities": found}}


def test_comparison_areas_in_open_water_move_ashore_or_are_left_out():
    # The site stands on a shore running north and south; west of it is sea.
    q = Shoreline(shore_lon=-73.0)
    centres = asyncio.run(engine.land_centres(q, 40.0, -72.99, 700, 2500, engine.REF_BEARINGS))
    assert centres and all(lon >= -73.0 for _, lon in centres)  # never a centre at sea
    # East-facing bearings keep their own point; the due-west one (270° is not a bearing, 240° and 300° are) has no
    # land within its alternatives and is left out, and alternatives never stack on top of another centre.
    own = {engine.offset_point(40.0, -72.99, 2500, b) for b in (0, 60, 120, 180)}
    assert own <= set(centres) and len(centres) < len(engine.REF_BEARINGS)
    assert all(engine.distance_m_between(a, b) >= 700 for i, a in enumerate(centres) for b in centres[i + 1:])


def test_a_populated_bearing_costs_one_question():
    q = Shoreline(shore_lon=-180.0)
    centres = asyncio.run(engine.land_centres(q, 40.0, -73.0, 700, 2500, engine.REF_BEARINGS))
    assert len(centres) == len(q.asked) == len(engine.REF_BEARINGS)


def test_supply_is_counted_inside_the_longer_walk_and_its_area_scales_it():
    ring = circle_ring(40.0, -73.0, 800)
    around = circle_ring(40.0, -73.0, 1200)  # a 20-minute walk cut short by water: smaller than twice the radius
    walk = Catchment(40.0, -73.0, 10, "street network", ring, around)
    assert engine.around_filter(walk) == {"filter.location": walk.around_wkt, "filter.location.radius": 0}
    assert math.isclose(engine.around_area_m2(walk), math.pi * 1200 ** 2, rel_tol=0.02)
    assert walk.around_minutes == 20
    # Without routing, supply falls back to a circle twice the walk's radius.
    fallback = circle_catchment(40.0, -73.0, 10)
    assert engine.around_filter(fallback) == {"filter.location": point_wkt(40.0, -73.0),
                                              "filter.location.radius": engine.around_radius(fallback)}
    assert math.isclose(engine.around_area_m2(fallback), math.pi * engine.around_radius(fallback) ** 2)
