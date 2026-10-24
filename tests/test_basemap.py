"""The kit's street map: what one Overpass query reads around a walk, how its streets, water and parks are cut to a box,
which side of a shore is water, how the client asks and caches, and how the vector tiles stand in when Overpass does not
answer. Fake Overpass answers and fake tiles only."""
import asyncio
import json
import math

import httpx
import pytest

from app import basemap, osm, vectortiles
from app.catchment import Catchment

SITE = (40.7145, -73.958)
M = 111_320.0
KX = M * math.cos(math.radians(SITE[0]))
ENDPOINTS = ("https://first.test/api/interpreter", "https://second.test/api/interpreter")


def at(east: float, north: float) -> dict:
    """An Overpass node `east` and `north` metres from the site."""
    return {"lat": SITE[0] + north / M, "lon": SITE[1] + east / KX}


def ring_at(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A (lon, lat) ring, as the catchment stores it, through points given in metres."""
    ring = [(SITE[1] + e / KX, SITE[0] + n / M) for e, n in points]
    return ring + [ring[0]]


# A diamond walk reaching 800 m: the box is its bounds plus 480 m, widened to 1.8 times its height.
WALK = Catchment(*SITE, 10, "street network", ring_at([(-800, 0), (0, 800), (800, 0), (0, -800)]))
BOX = basemap.box_for(WALK)
WALK_M = [BOX.metres(lat, lon) for lon, lat in WALK.ring]


def way(nodes: list[dict | None], **tags: str) -> dict:
    return {"type": "way", "id": len(tags) + len(nodes), "geometry": nodes, "tags": tags}


def street(points: list[tuple[float, float]], kind: str = "residential") -> dict:
    return way([at(*p) for p in points], highway=kind)


def relation(members: list[tuple[str, list[dict | None]]], **tags: str) -> dict:
    return {"type": "relation", "id": 9, "tags": tags,
            "members": [{"type": "way", "ref": i, "role": role, "geometry": nodes} for i, (role, nodes) in enumerate(members)]}


def answer(*elements: dict) -> dict:
    """An Overpass answer with a main street, so it is never rejected as empty, and the given elements."""
    return {"osm3s": {"timestamp_osm_base": "2026-10-23T17:33:41Z"},
            "elements": [street([(-3000, 300), (3000, 300)], "primary"), *elements]}


def wet(layers: basemap.Layers, east: float, north: float) -> bool:
    return basemap.winding((east, north), layers.water) != 0


# ---------- The box and the query ----------

def test_the_box_is_the_walk_plus_60_percent_of_its_reach_widened_for_a_wide_frame():
    assert (BOX.south, BOX.north) == pytest.approx((-1280, 1280), abs=0.5)
    assert (BOX.west, BOX.east) == pytest.approx((-2304, 2304), abs=0.5)
    south, west, north, east = BOX.bbox
    assert south < SITE[0] < north and west < SITE[1] < east
    assert BOX.metres(*BOX.degrees((1000.0, -500.0))) == pytest.approx((1000, -500), abs=1)


def test_one_query_reads_streets_water_and_parks_with_their_geometry_cut_to_the_box():
    query = basemap.query(BOX)
    area = "({:.5f},{:.5f},{:.5f},{:.5f})".format(*BOX.bbox)
    assert query.startswith("[out:json][timeout:25][maxsize:")
    assert query.endswith(f");out geom{area} qt;")
    statements = query.split("(", 1)[1].rsplit(");out", 1)[0].split(";")
    assert [s for s in statements if s] == [
        f'way["highway"~"^({basemap.STREETS})$"]{area}', f'way["natural"~"^(water|coastline)$"]{area}',
        f'way["leisure"="park"]{area}', f'rel["leisure"="park"]{area}', f'way["waterway"="riverbank"]{area}',
        f'rel["natural"="water"]{area}', f'rel["waterway"="riverbank"]{area}',
    ]
    assert "footway" not in basemap.STREETS and "service" not in basemap.STREETS and "pedestrian" in basemap.STREETS


# ---------- Streets ----------

def test_streets_are_cut_at_the_box_kept_by_rank_and_joined_where_one_way_goes_on_as_another():
    data = answer(
        street([(-3000, -100), (3000, -100)], "trunk"),
        # One street split into three ways, block by block, with a node on every corner.
        street([(-600, -500), (-300, -500), (0, -500)]), street([(0, -500), (300, -500)]),
        street([(300, -500), (600, -500)]),
        # Two streets crossing, each split at the crossing: two lines, not one and not four.
        street([(1000, -900), (1000, -600)]), street([(1000, -600), (1000, -300)]),
        street([(700, -600), (1000, -600)]), street([(1000, -600), (1300, -600)]),
        street([(0, 900), (0, 1100)], "pedestrian"),
        way([at(0, 0), at(10, 10)], highway="footway"),
    )
    layers = basemap.read(data, BOX, WALK_M)
    simple = layers.simplified(2.0)
    primary = simple.streets["primary"]
    assert len(primary) == 2 and all(line[0][0] == pytest.approx(BOX.west) and line[-1][0] == pytest.approx(BOX.east)
                                     for line in primary)
    residential = sorted(simple.streets["residential"])
    assert [(round(a[0]), round(a[1]), round(b[0]), round(b[1])) for a, b in residential[:1]] == [(-600, -500, 600, -500)]
    assert len(residential) == 3 and all(len(line) == 2 for line in residential)
    assert len(simple.streets["pedestrian"]) == 1 and simple.streets["secondary"] == []


def test_a_stretch_of_way_the_box_cut_short_is_read_as_overpass_gives_it():
    nodes = [None, None, at(-3000, 0), at(-1000, 0), at(1000, 0), at(3000, 0), None, at(-3000, 600), at(3000, 600)]
    runs = basemap.runs_of(nodes, BOX)
    assert [len(run) for run in runs] == [4, 2]
    assert basemap.runs_of([at(0, 0), at(0, 0), at(5, 0)], BOX) == [[(0.0, 0.0), pytest.approx((5.0, 0.0))]]


# ---------- Water ----------

COAST_NORTH = [at(1500, -2000), at(1500, -1000), at(1500, 0), at(1500, 1000), at(1500, 2000)]


@pytest.mark.parametrize("nodes", [COAST_NORTH, COAST_NORTH[::-1]], ids=["as mapped", "drawn backwards"])
def test_the_sea_is_on_the_far_side_of_the_coastline_from_the_site(nodes):
    layers = basemap.read(answer(way(nodes[:3], natural="coastline"), way(nodes[2:], natural="coastline")), BOX, WALK_M)
    assert len(layers.water) == 1
    assert wet(layers, 2000, 0) and wet(layers, 1600, 1200) and wet(layers, 2290, -1270)
    assert not wet(layers, 0, 0) and not wet(layers, 1400, 0) and not wet(layers, -2000, 0)
    assert basemap.area_m2(layers.water[0]) == pytest.approx((BOX.east - 1500) * (BOX.north - BOX.south), rel=1e-6)


def test_a_river_whose_banks_run_beyond_the_box_is_water_between_them():
    north_bank = [None, at(-3000, -1000), at(-1500, -1000), at(0, -1000), at(1500, -1000), at(3000, -1000), None]
    south_bank = [None, at(3000, -1200), at(1500, -1200), at(-1500, -1200), at(-3000, -1200), None]
    river = relation([("outer", north_bank), ("outer", south_bank), ("outer", [None, None]), ("outer", [])],
                     natural="water", water="river")
    layers = basemap.read(answer(river), BOX, WALK_M)
    assert wet(layers, 0, -1100) and wet(layers, -2200, -1150) and wet(layers, 2200, -1050)
    assert not wet(layers, 0, -900) and not wet(layers, 0, -1250) and not wet(layers, 0, 0)


def test_islands_are_holes_and_a_lake_is_water():
    outer = [at(1200, 200), at(2200, 200), at(2200, 1100), at(1200, 1100), at(1200, 200)]
    island = [at(1500, 500), at(1500, 800), at(1800, 800), at(1800, 500), at(1500, 500)]
    lake = way([at(-2000, -900), at(-1700, -900), at(-1700, -700), at(-2000, -700), at(-2000, -900)], natural="water")
    layers = basemap.read(answer(relation([("outer", outer), ("inner", island)], natural="water"), lake), BOX, WALK_M)
    assert wet(layers, 1300, 300) and wet(layers, 2100, 1000) and wet(layers, -1850, -800)
    assert not wet(layers, 1650, 650) and not wet(layers, 0, 0)


def test_a_site_on_an_island_has_water_all_around_it():
    shore = [at(-2000, -1200), at(2000, -1200), at(2000, 1200), at(-2000, 1200), at(-2000, -1200)]
    island = [at(-1000, -1000), at(-1000, 1000), at(1000, 1000), at(1000, -1000), at(-1000, -1000)]
    layers = basemap.read(answer(relation([("outer", shore), ("inner", island)], natural="water")), BOX, WALK_M)
    assert wet(layers, 1500, 0) and wet(layers, -1500, 1100) and wet(layers, 0, -1100)
    assert not wet(layers, 0, 0) and not wet(layers, 800, 0) and not wet(layers, 2200, 0)


def test_water_whose_edges_do_not_close_or_that_would_cover_the_walk_is_left_out():
    stray = way([at(-500, -1000), at(500, -1100)], natural="water")  # an edge that stops inside the box
    around_the_site = way([at(-1000, -1000), at(1000, -1000), at(1000, 1000), at(-1000, 1000), at(-1000, -1000)],
                          waterway="riverbank")
    layers = basemap.read(answer(stray, around_the_site), BOX, WALK_M)
    assert layers.water == []


# ---------- Parks ----------

def test_parks_inside_the_box_are_kept_and_those_it_cuts_are_left_out():
    park = way([at(-600, 400), at(-300, 400), at(-300, 650), at(-600, 650), at(-600, 400)], leisure="park")
    cut = way([at(2000, 1000), at(2600, 1000), at(2600, 1500), at(2000, 1500), at(2000, 1000)], leisure="park")
    layers = basemap.read(answer(park, cut), BOX, WALK_M)
    assert len(layers.parks) == 1 and basemap.area_m2(layers.parks[0]) == pytest.approx(300 * 250, rel=1e-6)


# ---------- The payload ----------

def test_a_kit_keeps_lat_lon_lines_and_rings_capped_at_max_points(monkeypatch):
    grid = [street([(-2000, y), (-1000, y + 3), (0, y), (1000, y + 3), (2000, y)]) for y in range(-1200, 1200, 100)]
    park = way([at(-600, 400), at(-300, 400), at(-300, 650), at(-600, 650), at(-600, 400)], leisure="park")
    data = answer(*grid, park, street([(0, -50), (0, 50)], "pedestrian"))
    kept = basemap.shape(data, BOX, WALK_M)
    assert kept["dropped"] == [] and kept["thinned"] == [] and kept["points"] <= basemap.MAX_POINTS
    assert kept["box"] == [[pytest.approx(v) for v in BOX.bbox[:2]], [pytest.approx(v) for v in BOX.bbox[2:]]]
    lat, lon = kept["streets"]["primary"][0][0]
    assert (round(lat, 5), round(lon, 5)) == (lat, lon) and abs(lat - SITE[0]) < 0.02
    assert kept["credit"] == "© OpenStreetMap contributors" and len(kept["parks"]) == 1
    # Too many points even at the coarsest tolerance (a dense old city): the main roads and parks stay, and the lesser
    # streets fill what is left, longest first; here the short pedestrian street has no room left.
    monkeypatch.setattr(basemap, "MAX_POINTS", 40)
    small = basemap.shape(data, BOX, WALK_M)
    assert small["thinned"] == ["residential"] and small["dropped"] == ["pedestrian"] and small["points"] <= 40
    assert small["streets"]["primary"] and len(small["parks"]) == 1 and small["tolerance_m"] == basemap.TOLERANCES_M[-1]
    assert len(small["streets"]["residential"]) == (40 - 2 - 5) // 2
    assert json.loads(json.dumps(small)) == small


def test_thinning_keeps_the_longest_streets_and_those_across_the_area_first(monkeypatch):
    monkeypatch.setattr(basemap, "MAX_POINTS", 2 + 2 * 2)
    far_long = street([(-2200, -1100), (-200, -1100)])  # 2 km, far from the walk
    near_short = street([(-300, 100), (300, 100)])  # 600 m across the walk: counts double
    far_short = street([(1500, 1000), (2100, 1000)])  # 600 m, far
    kept = basemap.shape(answer(far_long, near_short, far_short), BOX, WALK_M)
    lines = sorted(round(line[0][1], 4) for line in kept["streets"]["residential"])
    assert len(lines) == 2 and kept["thinned"] == ["residential"]
    expected = sorted(round(at(*p)["lon"], 4) for p in ((-2200, -1100), (-300, 100)))
    assert lines == expected


def test_an_answer_without_streets_is_no_street_map():
    with pytest.raises(osm.OsmError):
        basemap.shape({"elements": [way(COAST_NORTH, natural="coastline")]}, BOX, WALK_M)


def test_a_large_area_can_ask_for_the_main_roads_only():
    query = basemap.query(BOX, ("primary",))
    assert '"highway"~"^(motorway|trunk|primary)$"' in query and "residential" not in query
    assert "leisure" not in query and '["water"~"^(river|lake|reservoir|lagoon|canal|oxbow)$"]' in query
    data = answer(street([(-600, -500), (600, -500)]), street([(-3000, -100), (3000, -100)], "secondary"))
    kept = basemap.shape(data, BOX, WALK_M, ("primary",))
    assert kept["layers"] == ["primary"] and kept["streets"]["primary"]
    assert kept["streets"]["secondary"] == [] and kept["streets"]["residential"] == []
    assert basemap.shape(data, BOX, WALK_M)["layers"] == list(basemap.STREET_LAYERS)
    # The street layers go by the area's size: every street to 10 km², the main roads to 60 km², the arterials beyond.
    assert WALK.area_m2 < 10e6 and basemap.layers_for(WALK) == basemap.STREET_LAYERS and basemap.layers_for(None) == basemap.STREET_LAYERS
    town = Catchment(*SITE, 20, "street network", ring_at([(-2500, 0), (0, 2500), (2500, 0), (0, -2500)]), travel="drive")
    assert 10e6 < town.area_m2 < 60e6 and basemap.layers_for(town) == ("primary", "secondary")
    assert basemap.highways(basemap.layers_for(town)) == "motorway|trunk|primary|secondary|tertiary"
    region = Catchment(*SITE, 60, "street network", ring_at([(-9000, 0), (0, 8000), (9000, 0), (0, -8000)]), travel="drive")
    assert region.area_m2 > 60e6 and basemap.layers_for(region) == ("primary",)


def test_a_big_drive_asks_for_its_arterials_and_its_map_stays_small(tmp_path):
    reach = 30_000  # a 60-minute drive: an area of 1,800 km² and a box over 100 km wide
    drive = Catchment(*SITE, 60, "street network", ring_at([(-reach, 0), (0, reach), (reach, 0), (0, -reach)]),
                      travel="drive", km=None)
    box = basemap.box_for(drive)
    # A region's arterials, each a long line with a bend every 50 m: far more points than any map should carry.
    roads = [street([(x, -40_000 + 50 * k + (x % 7)) for k in range(1600)], "primary") for x in range(-60_000, 60_000, 4000)]
    lake = way([at(-5000, 5000), at(-3000, 5000), at(-3000, 6500), at(-5000, 6500), at(-5000, 5000)], natural="water",
               water="lake")
    client_, seen = client(tmp_path, answer(*roads, lake))
    streets = asyncio.run(basemap.street_map(client_, drive, basemap.layers_for(drive)))
    sent = seen[0].content.decode()
    assert "motorway%7Ctrunk%7Cprimary%29" in sent and "residential" not in sent and "leisure" not in sent
    assert streets["layers"] == ["primary"] and streets["streets"]["primary"] and len(streets["water"]) == 1
    assert streets["points"] <= basemap.MAX_POINTS and len(json.dumps(streets)) < 60_000
    assert streets["tolerance_m"] > basemap.TOLERANCES_M[-1]  # simplified harder than a walk's map
    assert (box.east - box.west) > 100_000


# ---------- The client ----------

def client(tmp_path, *answers) -> tuple[osm.OsmClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    queue = list(answers)

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        reply = queue.pop(0) if queue else 504
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply) if isinstance(reply, dict) else httpx.Response(reply)

    return osm.OsmClient(tmp_path, ENDPOINTS, transport=httpx.MockTransport(handle)), seen


def test_one_query_per_walk_asked_like_the_cross_check_and_kept_on_disk(tmp_path):
    coast = way(COAST_NORTH, natural="coastline")
    client_, seen = client(tmp_path, answer(coast), answer())
    streets = asyncio.run(basemap.street_map(client_, WALK))
    assert streets["source"] == "first.test" and streets["as_of"] == "2026-10-23T17:33:41Z"
    assert streets["streets"]["primary"] and len(streets["water"]) == 1
    request = seen[0]
    assert request.method == "POST" and "github.com/AhmedOsamaAli/walk-in" in request.headers["user-agent"]
    assert b"out+geom%28" in request.content
    [saved] = tmp_path.glob("*.json")
    assert saved.name.startswith("basemap-")
    # A second kit for the same walk reads the map from the disk.
    assert asyncio.run(basemap.street_map(client_, WALK)) == streets and len(seen) == 1
    # Another road class is another query.
    main_roads = asyncio.run(basemap.street_map(client_, WALK, ("primary",)))
    assert main_roads["layers"] == ["primary"] and len(seen) == 2 and len(list(tmp_path.glob("*.json"))) == 2


def test_an_instance_whose_answer_holds_no_street_gives_way_to_the_next(tmp_path):
    client_, seen = client(tmp_path, {"elements": []}, answer())
    streets = asyncio.run(basemap.street_map(client_, WALK))
    assert streets["source"] == "second.test" and len(seen) == 2


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("refused"), 502, {"elements": [], "remark": "runtime error: Query timed out"},
])
def test_without_an_answer_the_kit_has_no_street_map_and_nothing_is_made_up(tmp_path, failure):
    client_, seen = client(tmp_path, failure, failure)
    assert asyncio.run(basemap.street_map(client_, WALK)) is None
    assert len(seen) == 2 and not list(tmp_path.glob("*.json"))


def test_no_client_or_no_walk_is_no_street_map(tmp_path):
    client_, seen = client(tmp_path, answer())
    assert asyncio.run(basemap.street_map(None, WALK)) is None
    assert asyncio.run(basemap.street_map(client_, None)) is None
    assert seen == []


# ---------- The second source: vector tiles (app.vectortiles) ----------

class FakeTiles:
    """Stands in for app.vectortiles.TileClient: records what it is asked, answers a map or fails."""

    def __init__(self, fail: BaseException | None = None) -> None:
        self.fail = fail
        self.asked: list[tuple[basemap.Box, tuple[str, ...]]] = []

    async def street_map(self, box, walk, layers):
        self.asked.append((box, tuple(layers)))
        if self.fail is not None:
            raise self.fail
        return {"source": vectortiles.SOURCE, "layers": list(layers), "streets": {"primary": [[[0, 0], [1, 1]]]},
                "credit": vectortiles.CREDIT}


class DownOverpass:
    """An Overpass client that never answers, and records how it was asked."""

    def __init__(self) -> None:
        self.asked: list[dict] = []

    async def ask(self, query, shape, **options):
        self.asked.append(options)
        raise osm.OsmError("every instance timed out")


def test_when_overpass_does_not_answer_the_tiles_draw_the_map(tmp_path):
    client_, seen = client(tmp_path, 502, 502)
    tiles = FakeTiles()
    streets = asyncio.run(basemap.street_map(client_, WALK, tiles=tiles))
    assert streets["source"] == "tiles.openfreemap.org" and streets["credit"] == vectortiles.CREDIT
    assert len(seen) == 2 and tiles.asked == [(BOX, basemap.STREET_LAYERS)]  # Overpass first, then the same box
    town = Catchment(*SITE, 20, "street network", ring_at([(-2500, 0), (0, 2500), (2500, 0), (0, -2500)]), travel="drive")
    asyncio.run(basemap.street_map(client_, town, basemap.layers_for(town), tiles))
    assert tiles.asked[-1] == (basemap.box_for(town), basemap.MAIN_ROADS)  # the layers the area's size calls for
    # Without Overpass at all, the tiles still draw it.
    assert asyncio.run(basemap.street_map(None, WALK, tiles=tiles))["source"] == "tiles.openfreemap.org"


def test_overpass_comes_first_and_gets_forty_seconds_before_the_tiles(tmp_path):
    client_, seen = client(tmp_path, answer())
    tiles = FakeTiles()
    assert asyncio.run(basemap.street_map(client_, WALK, tiles=tiles))["source"] == "first.test" and tiles.asked == []
    down = DownOverpass()
    assert asyncio.run(basemap.street_map(down, WALK, tiles=tiles))["source"] == "tiles.openfreemap.org"
    assert down.asked == [{"name": "basemap", "timeout": basemap.TIMEOUT_S, "budget": 40.0}]
    assert basemap.BUDGET_S + vectortiles.BUDGET_S <= 70  # a kit's street map is ready in about a minute at worst


def test_tiles_first_asks_overpass_only_when_the_tiles_fail(tmp_path):
    client_, seen = client(tmp_path, answer())
    tiles = FakeTiles()
    assert asyncio.run(basemap.street_map(client_, WALK, tiles=tiles, tiles_first=True))["source"] == "tiles.openfreemap.org"
    assert seen == [] and len(tiles.asked) == 1
    failing = FakeTiles(vectortiles.TileError("tile 14/1/1: HTTP 502"))
    assert asyncio.run(basemap.street_map(client_, WALK, tiles=failing, tiles_first=True))["source"] == "first.test"
    assert len(seen) == 1 and len(failing.asked) == 1


@pytest.mark.parametrize("failure", [
    vectortiles.TileError("the tiles took longer than 30 s"), ValueError("odd"), KeyError("tiles"), TimeoutError(),
    httpx.ConnectError("refused"),
])
def test_the_street_map_never_raises_and_is_none_when_both_sources_fail(tmp_path, failure):
    client_, seen = client(tmp_path, 502, 502)
    tiles = FakeTiles(failure)
    assert asyncio.run(basemap.street_map(client_, WALK, tiles=tiles)) is None
    assert len(seen) == 2 and len(tiles.asked) == 1 and not list(tmp_path.glob("*.json"))
    assert asyncio.run(basemap.street_map(None, WALK, tiles=FakeTiles(failure), tiles_first=True)) is None
    odd = Catchment(*SITE, 10, "street network", [("east", "north")] * 5)  # an area no box can be drawn around
    assert asyncio.run(basemap.street_map(client_, odd, tiles=FakeTiles())) is None


def test_an_area_is_cut_to_the_box_winding_as_it_did():
    box = basemap.Box(*SITE, -100, -100, 100, 100)
    # A U open to the north, through the box's north edge: one ring, its arms joined along the edge by a line of no
    # width, filling the bar and the two arms inside the box.
    u = [(-150, -50), (150, -50), (150, 150), (50, 150), (50, 0), (-50, 0), (-50, 150), (-150, 150), (-150, -50)]
    cut = basemap.clip_area(u, box)
    assert cut[0] == cut[-1] and all(box.inside(p) for p in cut)
    assert basemap.area_m2(cut) == pytest.approx(200 * 50 + 2 * 50 * 100)
    assert basemap.winding((0, 50), [cut]) == 0 and basemap.winding((-75, 50), [cut]) == 1
    hole = [(-20, -20), (-20, 20), (20, 20), (20, -20), (-20, -20)]  # clockwise, wholly inside: as it was
    assert basemap.clip_area(hole, box) == hole and basemap.area_m2(hole) < 0
    assert basemap.clip_area([(200, 200), (300, 200), (300, 300), (200, 300), (200, 200)], box) == []
    whole = basemap.clip_area([(-500, -500), (500, -500), (500, 500), (-500, 500), (-500, -500)], box)
    assert basemap.area_m2(whole) == pytest.approx(200 * 200)
