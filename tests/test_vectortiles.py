"""The street map's second source: OpenFreeMap's vector tiles (app.vectortiles). Tiles are made here by a minimal Mapbox
Vector Tile encoder and served by a fake OpenFreeMap; nothing is downloaded."""
import asyncio
import gzip
import json
import math
import os
import struct
import time

import httpx
import pytest

from app import basemap, osm
from app import vectortiles as vt
from app.basemap import Box

# ---------- A minimal MVT 2.1 encoder ----------


def varint(number: int) -> bytes:
    out = bytearray()
    while True:
        byte, number = number & 0x7F, number >> 7
        out.append(byte | (0x80 if number else 0))
        if not number:
            return bytes(out)


def field(number: int, wire: int, payload: bytes | int) -> bytes:
    key = varint(number << 3 | wire)
    if wire == 0:
        return key + varint(payload)
    if wire in (1, 5):
        return key + payload
    return key + varint(len(payload)) + payload


def zigzag(number: int) -> int:
    return number * 2 if number >= 0 else -number * 2 - 1


def packed(numbers: list[int]) -> bytes:
    return b"".join(varint(number) for number in numbers)


def geometry(parts: list[list[tuple[int, int]]], rings: bool = False) -> list[int]:
    """Commands for lines, or for rings (given closed; ClosePath closes them)."""
    out: list[int] = []
    x = y = 0
    for part in parts:
        points = part[:-1] if rings else part
        out += [1 | 1 << 3, zigzag(points[0][0] - x), zigzag(points[0][1] - y)]
        x, y = points[0]
        out.append(2 | (len(points) - 1) << 3)
        for px, py in points[1:]:
            out += [zigzag(px - x), zigzag(py - y)]
            x, y = px, py
        if rings:
            out.append(7 | 1 << 3)
    return out


def value(item: object) -> bytes:
    if isinstance(item, bool):
        return field(7, 0, int(item))
    if isinstance(item, int):
        return field(5, 0, item) if item >= 0 else field(6, 0, zigzag(item))
    if isinstance(item, float):
        return field(3, 1, struct.pack("<d", item))
    return field(1, 2, str(item).encode())


def feature(kind: int, parts: list[list[tuple[int, int]]], raw: list[int] | None = None, **tags: object) -> tuple:
    return tags, kind, raw if raw is not None else geometry(parts, rings=kind == vt.POLYGON)


def layer(name: str, *features: tuple, extent: int = 4096, version_first: bool = False) -> bytes:
    keys: list[str] = []
    values: list[tuple[type, object]] = []
    body = b""
    for tags, kind, commands in features:
        ints: list[int] = []
        for key, item in tags.items():
            if key not in keys:
                keys.append(key)
            if (type(item), item) not in values:
                values.append((type(item), item))
            ints += [keys.index(key), values.index((type(item), item))]
        body += field(2, 2, field(1, 0, 7) + field(2, 2, packed(ints)) + field(3, 0, kind) + field(4, 2, packed(commands)))
    body += b"".join(field(3, 2, key.encode()) for key in keys)
    body += b"".join(field(4, 2, value(item)) for _, item in values)
    head = field(1, 2, name.encode())
    body = (field(15, 0, 2) + head if version_first else head + field(15, 0, 2)) + body + field(5, 0, extent)
    return field(3, 2, body)


# ---------- Two tiles side by side, at zoom 14 ----------

Z = 14
N = 1 << Z
COLUMN, ROW = 4825, 6160  # Williamsburg
SITE = (math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ROW + 0.5) / N)))), (COLUMN + 1) / N * 360 - 180)
BOX = Box(*SITE, -800.0, -400.0, 800.0, 400.0)
WALK = [(-300.0, 0.0), (0.0, 300.0), (300.0, 0.0), (0.0, -300.0), (-300.0, 0.0)]
VERSION = "20261018_080001_pt"
TILEJSON = {"tilejson": "3.0.0", "name": "OpenFreeMap", "minzoom": 0, "maxzoom": 14,
            "tiles": [f"https://tiles.test/planet/{VERSION}/{{z}}/{{x}}/{{y}}.pbf"]}


def units(east: float, north: float, column: int) -> tuple[int, int]:
    """Tile coordinates, in tile (column, ROW), of the point `east` and `north` metres from the site."""
    lat, lon = SITE[0] + north / 111_320.0, SITE[1] + east / BOX.kx
    fx = (lon + 180) / 360
    fy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2
    return round(fx * N * 4096 - column * 4096), round(fy * N * 4096 - ROW * 4096)


def across(north: float, west_east: tuple[float, float], nudge: int = 0) -> tuple[list, list]:
    """A line at `north` from west to east across the shared edge, as two tiles carry it: each to 64 units past the
    edge, where the west tile's copy ends a unit off (two tiles' copies differ past the edge)."""
    a, b = units(west_east[0], north, COLUMN), units(west_east[1], north, COLUMN + 1)
    return [a, (4096 + 64, a[1] + nudge)], [(-64, b[1]), b]


def rect(west: float, south: float, east: float, north: float, column: int, clip: tuple[int, int] = (-64, 4160)) -> list:
    """An outer ring (clockwise on screen, as MVT 2 winds them) around the metres given, cut 64 units past the tile."""
    (x1, y1), (x2, y2) = units(west, north, column), units(east, south, column)
    x1, x2 = max(x1, clip[0]), min(x2, clip[1])
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]


def tiles() -> dict[tuple[int, int], bytes]:
    street_west, street_east = across(100.0, (-700.0, 700.0), nudge=1)
    road_west, road_east = across(-150.0, (-700.0, 700.0))
    island = [units(100, -330, COLUMN + 1), units(150, -330, COLUMN + 1), units(150, -300, COLUMN + 1),
              units(100, -300, COLUMN + 1)]
    island.append(island[0])  # counterclockwise on screen: a hole
    west = (
        layer("poi", feature(vt.POINT, [], raw=[5, 0, 0], **{"class": "cafe"})),  # unreadable, and never read
        layer("transportation",
              feature(vt.LINE, [street_west], **{"class": "minor"}),
              feature(vt.LINE, [road_west], **{"class": "primary", "brunnel": "bridge"}),
              feature(vt.LINE, [[units(-700, 300, COLUMN), units(-200, 300, COLUMN)]], **{"class": "motorway", "ramp": 1}),
              feature(vt.LINE, [], raw=[5, 0, 0], **{"class": "service"}),  # skipped by its tags, geometry unread
              feature(vt.LINE, [[units(-600, -300, COLUMN), units(-500, -300, COLUMN)]], **{"class": "path", "subclass": "footway"})),
        layer("water",
              feature(vt.POLYGON, [rect(-300, -380, 2000, -250, COLUMN)], **{"class": "lake"}),
              feature(vt.POLYGON, [rect(-700, 200, -650, 260, COLUMN)], **{"class": "swimming_pool"})),
        layer("landcover",
              feature(vt.POLYGON, [rect(-600, 200, -400, 350, COLUMN)], **{"class": "grass", "subclass": "park"}),
              feature(vt.POLYGON, [rect(-350, 200, -300, 250, COLUMN)], **{"class": "grass", "subclass": "garden"}),
              version_first=True),
        layer("park", feature(vt.POLYGON, [rect(-800, -400, 0, 400, COLUMN)], **{"class": "nature_reserve"})),
    )
    east = (
        layer("transportation",
              feature(vt.LINE, [street_east], **{"class": "minor"}),
              feature(vt.LINE, [road_east], **{"class": "primary"}),
              feature(vt.LINE, [[units(200, 250, COLUMN + 1), units(400, 250, COLUMN + 1)]], **{"class": "path", "subclass": "pedestrian"}),
              feature(vt.POLYGON, [rect(500, 250, 600, 350, COLUMN + 1)], **{"class": "path", "subclass": "pedestrian"})),
        layer("water", feature(vt.POLYGON, [rect(-2000, -380, 300, -250, COLUMN + 1), island], **{"class": "lake"})),
    )
    return {(COLUMN, ROW): b"".join(west), (COLUMN + 1, ROW): b"".join(east)}


def openfreemap(served: dict[tuple[int, int], bytes] | None = None, status: dict | None = None, seen: list | None = None):
    """A fake OpenFreeMap: the TileJSON and the tiles, one of them gzip as declared, the other gzip undeclared."""
    served = tiles() if served is None else served
    status = status or {}

    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == "/planet":
            return httpx.Response(status.get("tilejson", 200), json=TILEJSON)
        z, x, y = (int(part) for part in path.removesuffix(".pbf").split("/")[-3:])
        if (x, y) in status:
            return httpx.Response(status[(x, y)])
        if z != Z or (x, y) not in served:
            return httpx.Response(404)
        packed_tile = gzip.compress(served[(x, y)])
        if x == COLUMN:
            return httpx.Response(200, content=packed_tile, headers={"content-encoding": "gzip"})
        return httpx.Response(200, content=packed_tile)

    return httpx.MockTransport(handle)


def client(tmp_path, **options) -> tuple[vt.TileClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []
    transport = openfreemap(options.pop("served", None), options.pop("status", None), seen)
    return vt.TileClient(tmp_path, "https://tiles.test/planet", transport=transport, **options), seen


def street_map(tiles_client: vt.TileClient, box: Box = BOX, layers=basemap.STREET_LAYERS) -> dict:
    return asyncio.run(tiles_client.street_map(box, WALK, layers))


def metres(line: list[list[float]]) -> list[tuple[float, float]]:
    return [BOX.metres(lat, lon) for lat, lon in line]


# ---------- Reading a tile ----------

def test_a_tile_is_read_only_as_far_as_the_map_needs():
    found = vt.read_tile(tiles()[(COLUMN, ROW)], vt.targets(basemap.STREET_LAYERS))
    names = sorted(name for name, *_ in found)
    # No poi, no ramp, no service road or footway, no pool or garden, no nature reserve: and the poi layer and the
    # service road, whose geometry cannot be read, were skipped unread.
    assert names == ["park", "primary", "residential", "water"]
    name, kind, extent, parts = next(item for item in found if item[0] == "residential")
    assert (kind, extent) == (vt.LINE, 4096) and parts == [list(across(100.0, (-700.0, 700.0), nudge=1)[0])]
    water = next(item for item in found if item[0] == "water")
    assert water[3] == [rect(-300, -380, 2000, -250, COLUMN)]  # a ring, closed


def test_tag_values_of_every_type_are_read():
    def tags_of(tile: bytes) -> list[dict]:
        seen: list[dict] = []
        vt.read_tile(tile, {"transportation": lambda tags, kind: seen.append(tags)})
        return seen

    for item in ("text", 7, -3, True, 2.5):
        tile = layer("transportation", feature(vt.LINE, [[(0, 0), (5, 5)]], **{"class": "minor", "subclass": item}))
        assert tags_of(tile) == [{"class": "minor", "subclass": item}]
    # Only the tags the map reads (vt.KEYS).
    tile = layer("transportation", feature(vt.LINE, [[(0, 0), (5, 5)]], **{"class": "minor", "name": "Bedford Avenue"}))
    assert tags_of(tile) == [{"class": "minor"}]


def test_a_broken_tile_is_a_tile_error():
    tile = tiles()[(COLUMN, ROW)]
    with pytest.raises(vt.TileError):
        vt.read_tile(tile[:len(tile) // 2], vt.targets(basemap.STREET_LAYERS))
    with pytest.raises(vt.TileError):
        vt.read_tile(field(3, 2, field(1, 2, b"water") + bytes([0x0F, 0x00])), vt.targets(basemap.STREET_LAYERS))
    with pytest.raises(vt.TileError):  # a wanted feature whose geometry cannot be read
        vt.read_tile(layer("transportation", feature(vt.LINE, [], raw=[5, 0, 0], **{"class": "minor"})),
                     vt.targets(basemap.STREET_LAYERS))


# ---------- What the map draws ----------

def test_openmaptiles_classes_become_the_street_layers_asked_for():
    def street(layers, kind=vt.LINE, **tags):
        return vt.targets(layers)["transportation"](tags, kind)

    walk = basemap.STREET_LAYERS
    assert [street(walk, **{"class": kind}) for kind in ("motorway", "trunk", "primary", "secondary", "tertiary", "minor")] == [
        "primary", "primary", "primary", "secondary", "secondary", "residential"]
    assert street(walk, **{"class": "path", "subclass": "pedestrian"}) == "pedestrian"
    assert street(walk, vt.POLYGON, **{"class": "path", "subclass": "pedestrian"}) == "pedestrian"  # a square: its outline
    for tags in ({"class": "path", "subclass": "footway"}, {"class": "service"}, {"class": "track"},
                 {"class": "primary_construction"}, {"class": "motorway", "ramp": 1}, {"class": "rail"}):
        assert street(walk, **tags) is None, tags
    assert street(walk, vt.POLYGON, **{"class": "minor"}) is None and street(walk, vt.POINT, **{"class": "minor"}) is None
    # A town's map: the main roads; a region's: the arterials.
    assert street(basemap.MAIN_ROADS, **{"class": "tertiary"}) == "secondary"
    assert street(basemap.MAIN_ROADS, **{"class": "minor"}) is None
    assert street(basemap.MAIN_ROADS, **{"class": "path", "subclass": "pedestrian"}) is None
    assert street(basemap.ARTERIALS, **{"class": "secondary"}) is None and street(basemap.ARTERIALS, **{"class": "trunk"}) == "primary"


def test_water_and_parks_follow_the_overpass_map():
    walk, town = vt.targets(basemap.STREET_LAYERS), vt.targets(basemap.MAIN_ROADS)
    for kind in ("ocean", "lake", "river", "dock", "pond"):
        assert walk["water"]({"class": kind}, vt.POLYGON) == "water"
    assert walk["water"]({"class": "swimming_pool"}, vt.POLYGON) is None
    assert walk["water"]({"class": "lake"}, vt.LINE) is None
    assert [town["water"]({"class": kind}, vt.POLYGON) for kind in ("ocean", "lake", "river", "pond", "dock")] == [
        "water", "water", "water", None, None]
    # Parks: leisure=park, which OpenMapTiles keeps in landcover; only on a walk-sized map.
    assert walk["landcover"]({"class": "grass", "subclass": "park"}, vt.POLYGON) == "park"
    assert walk["landcover"]({"class": "grass", "subclass": "garden"}, vt.POLYGON) is None
    assert "landcover" not in town and "park" not in walk and "poi" not in walk


def test_the_zoom_keeps_a_walk_to_a_dozen_tiles_and_each_layer_where_openmaptiles_has_it():
    lat0, lon0 = 40.7135, -73.9625

    def box(width_km: float, height_km: float) -> Box:
        return Box(lat0, lon0, -width_km * 500, -height_km * 500, width_km * 500, height_km * 500)

    walk = basemap.STREET_LAYERS
    assert vt.zoom_for(box(4.6, 2.6), walk) == 14 and vt.tile_count(box(4.6, 2.6), 14) <= vt.MAX_TILES
    assert vt.zoom_for(box(9.2, 5.1), walk) == 13 and vt.tile_count(box(9.2, 5.1), 13) <= vt.MAX_TILES  # a 20-minute walk
    # Pedestrian streets start at 13: a box that needs more than a dozen tiles there takes more, up to MOST_TILES.
    assert vt.zoom_for(box(15, 8), walk) == 13 and vt.MAX_TILES < vt.tile_count(box(15, 8), 13) <= vt.MOST_TILES
    assert vt.zoom_for(box(30, 15), walk) == 12
    town, region = box(14.4, 8), box(173, 96)
    assert vt.zoom_for(town, basemap.MAIN_ROADS) == 12 and vt.tile_count(town, 12) <= vt.MAX_TILES
    zoom = vt.zoom_for(region, basemap.ARTERIALS)
    assert 7 <= zoom <= 9 and vt.tile_count(region, zoom) <= vt.MAX_TILES
    assert vt.tile_range(BOX, 14) == (COLUMN, ROW, COLUMN + 1, ROW)


# ---------- The map ----------

def test_the_tiles_make_a_map_shaped_like_an_overpass_map(tmp_path):
    tiles_client, seen = client(tmp_path)
    streets = street_map(tiles_client)
    assert streets["source"] == "tiles.openfreemap.org" and streets["as_of"] == "2026-10-18"
    assert streets["credit"] == vt.CREDIT and (streets["zoom"], streets["tiles"]) == (14, 2)
    assert set(streets) >= {"box", "layers", "streets", "water", "parks", "points", "tolerance_m", "dropped", "thinned"}
    assert streets["layers"] == list(basemap.STREET_LAYERS) and streets["points"] <= basemap.MAX_POINTS
    # Each street the tiles cut at their shared edge is one line again, edge to edge of the box's data.
    [residential] = streets["streets"]["residential"]
    [primary] = streets["streets"]["primary"]
    for line, north in ((residential, 100), (primary, -150)):
        assert len(line) == 2
        (x1, y1), (x2, y2) = metres(line)
        assert (x1, x2) == (pytest.approx(-700, abs=2), pytest.approx(700, abs=2)) and y1 == pytest.approx(north, abs=2)
    assert len(streets["streets"]["pedestrian"]) == 2 and streets["streets"]["secondary"] == []
    # One park; the lake from both tiles, with its island: no seam where the tiles meet.
    assert len(streets["parks"]) == 1 and basemap.area_m2(metres(streets["parks"][0])) > 0
    water = [metres(ring) for ring in streets["water"]]

    def wet(east: float, north: float) -> bool:
        return basemap.winding((east, north), water) != 0

    assert all(wet(east, north) for east in (-290, -1, 0, 1, 290) for north in (-370, -320, -260))
    assert not wet(125, -315)  # the island
    assert not any(wet(east, north) for east, north in ((-310, -300), (310, -300), (0, -240), (0, -390), (-675, 230)))
    assert all(request.headers["user-agent"] == osm.USER_AGENT for request in seen)
    assert [request.url.path for request in seen][0] == "/planet" and len(seen) == 3


def test_the_tiles_and_the_map_are_kept_on_disk(tmp_path):
    tiles_client, seen = client(tmp_path)
    streets = street_map(tiles_client)
    assert street_map(tiles_client) == streets and len(seen) == 3  # the shaped map, from the disk
    [saved] = tmp_path.glob("map-*.json")
    saved.unlink()
    assert street_map(tiles_client) == streets and len(seen) == 3  # the tiles, from the disk
    assert sorted(path.name for path in (tmp_path / VERSION).iterdir()) == [f"14-{COLUMN}-{ROW}.pbf", f"14-{COLUMN + 1}-{ROW}.pbf"]
    other, others_seen = client(tmp_path)  # another start: the TileJSON from the disk too
    assert street_map(other) == streets and others_seen == []
    # Another kind of map is another map.
    assert street_map(other, layers=basemap.MAIN_ROADS)["layers"] == ["primary", "secondary"] and others_seen == []


def test_an_old_tilejson_serves_when_openfreemap_does_not_answer(tmp_path):
    tiles_client, _ = client(tmp_path)
    street_map(tiles_client)
    for saved in tmp_path.glob("map-*.json"):
        saved.unlink()
    old = time.time() - 2 * vt.TILEJSON_MAX_AGE_S
    os.utime(tmp_path / "tilejson.json", (old, old))
    down, seen = client(tmp_path, status={"tilejson": 503})
    assert street_map(down)["source"] == "tiles.openfreemap.org" and [r.url.path for r in seen] == ["/planet"]


@pytest.mark.parametrize("status, problem", [
    ({(COLUMN + 1, ROW): 502}, "502"),
    ({"tilejson": 503}, "TileJSON"),
    ({(COLUMN, ROW): 404}, "1 of 2 tiles missing"),  # a map with a hole would hide a shore or streets
    ({(COLUMN, ROW): 404, (COLUMN + 1, ROW): 404}, "gone"),
])
def test_tiles_that_cannot_be_read_are_a_tile_error_and_no_map(tmp_path, status, problem):
    tiles_client, _ = client(tmp_path, status=status)
    with pytest.raises(vt.TileError, match=problem):
        street_map(tiles_client)
    assert not list(tmp_path.glob("map-*.json"))
    if problem == "gone":  # OpenFreeMap moved on: its TileJSON is read again next time
        assert not (tmp_path / "tilejson.json").exists()


def test_tiles_without_streets_are_no_map(tmp_path):
    served = {key: layer("water", feature(vt.POLYGON, [rect(-300, -380, 300, -250, key[0])], **{"class": "lake"}))
              for key in tiles()}
    tiles_client, _ = client(tmp_path, served=served)
    with pytest.raises(vt.TileError, match="no streets"):
        street_map(tiles_client)


def test_the_tiles_have_a_budget(tmp_path):
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200, json=TILEJSON)

    tiles_client = vt.TileClient(tmp_path, "https://tiles.test/planet", budget=0.2, transport=httpx.MockTransport(slow))
    started = time.monotonic()
    with pytest.raises(vt.TileError, match="longer than"):
        street_map(tiles_client)
    assert time.monotonic() - started < 2


def test_the_credit_is_openfreemaps_attribution_in_plain_text():
    assert vt.CREDIT == "OpenFreeMap © OpenMapTiles · Data © OpenStreetMap contributors"
    assert "<" not in vt.CREDIT and osm.CREDIT in vt.CREDIT


def test_a_kit_keeps_the_tile_map_small(tmp_path):
    tiles_client, _ = client(tmp_path)
    assert len(json.dumps(street_map(tiles_client))) < 60_000
