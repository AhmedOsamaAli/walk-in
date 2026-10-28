"""The kit's street map from vector tiles: its second source, for when no OpenStreetMap Overpass server answers in time
(app.basemap asks them first; when opening a kit saved without a street map, app.kits asks the tiles first).

OpenFreeMap (openfreemap.org) serves OpenStreetMap's data as vector tiles in the OpenMapTiles schema
(openmaptiles.org/schema), free and without a key. Its TileJSON (tiles.openfreemap.org/planet, kept a day) names the
current tiles; each is a Mapbox Vector Tile (MVT 2.1, protobuf; gzip on the wire, which httpx undoes), read here by a
small pure-Python decoder. Only what the map draws is decoded: the transportation, water and landcover layers (every
other layer is skipped by its length), and in those a feature's tags are read before its geometry, which is decoded only
for the classes the map draws:

- streets, as basemap's layers: motorway, trunk and primary roads are "primary", secondary and tertiary roads
  "secondary", minor roads (residential, unclassified, living streets) "residential", and paths of subclass pedestrian
  "pedestrian"; no ramps, roads under construction, service roads or footways, as in the Overpass query;
- water areas: the sea, lakes, rivers drawn as areas, docks and ponds (never pools); a map bigger than a walk only the
  sea, lakes and rivers;
- parks, on a walk-sized map only: OpenMapTiles keeps leisure=park in landcover (subclass "park"); its park layer holds
  nature reserves, protected areas and historic districts, which the Overpass map does not draw either.

The zoom is the highest, up to OpenMapTiles' 14, at which the box needs at most MAX_TILES tiles, but no lower than the
zoom that first carries the smallest street layer asked for (MIN_ZOOMS). Tile coordinates go through the world's grid
at that zoom to lon/lat and the box's metres, so a point two tiles share lands on the same metres in both. Streets are
cut at each tile's edge, and the cut ends two tiles share are joined again; areas are cut a little past the edge, so
neighbouring pieces overlap and, filled with the nonzero rule and no outline as the maps fill them, show no seam. Then
the map is simplified and capped as an Overpass map (basemap.payload), and credited as OpenFreeMap asks. A tile that
cannot be read or is missing fails the whole map (TileError): a map with a hole in it would hide a shore or streets.

OpenFreeMap's terms for downloads (openfreemap.org/quick_start): at most 4 requests at once and the app's own
User-Agent (app.osm's). Tiles are kept on disk for a week, and each shaped map too, so a survey's kits read them once.

Map © OpenFreeMap, © OpenMapTiles; data © OpenStreetMap contributors (ODbL).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import re
import struct
import time
import zlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import basemap, osm, tls
from .basemap import Box, Point

log = logging.getLogger("walkin")

TILEJSON_URL = "https://tiles.openfreemap.org/planet"
SOURCE = "tiles.openfreemap.org"
# OpenFreeMap's attribution, in plain text: its TileJSON's links to openfreemap.org, openmaptiles.org and
# openstreetmap.org/copyright, as the map's one line of credit.
CREDIT = "OpenFreeMap © OpenMapTiles · Data © OpenStreetMap contributors"

MAX_ZOOM = 14  # OpenMapTiles' most detailed tiles
MAX_TILES = 12  # a 10-minute walk's box at zoom 14
MOST_TILES = 30  # beyond this even the zoom that carries every layer asked for is too fine: a lower one, with fewer roads
PARALLEL = 4  # OpenFreeMap allows 4 requests at once
TRIES = 2
TIMEOUT_S = 10.0  # one tile
CONNECT_S = 5.0
BUDGET_S = 30.0  # the whole map: the TileJSON, every tile, decoding and shaping
TILEJSON_MAX_AGE_S = 24 * 3600
MAX_AGE_S = 7 * 24 * 3600  # tiles and shaped maps on disk
STALE_RETRY_S = 600.0  # an old TileJSON used because OpenFreeMap did not answer is asked for again after this long
OVERLAP = 4  # tile units (of 4096 a side) an area is kept past its tile's edge, so the next tile's piece overlaps it
SNAP_M = 1.0  # the ends of a street two tiles cut, on their shared edge within this distance of each other, are one point
_M_PER_DEG = 111_320.0

POINT, LINE, POLYGON = 1, 2, 3  # MVT geometry types
KEYS = frozenset({"class", "subclass", "ramp"})  # the only tags read

# OpenMapTiles' transportation classes (class/subclass for paths) as basemap's street layers.
STREET_CLASSES = {
    "motorway": "primary", "trunk": "primary", "primary": "primary",
    "secondary": "secondary", "tertiary": "secondary",
    "minor": "residential",
    "path/pedestrian": "pedestrian",
}
# The zoom from which OpenMapTiles carries each street layer: primary roads from 7, tertiary from 11, minor roads from
# 12, named pedestrian streets from 13 (all paths at 14).
MIN_ZOOMS = {"primary": 7, "secondary": 11, "residential": 12, "pedestrian": 13}
WALK_WATER = frozenset({"ocean", "lake", "river", "dock", "pond"})
BIG_WATER = frozenset({"ocean", "lake", "river"})  # a region's ponds would outnumber its roads, as in basemap.BIG_WATER
PARK = "park"  # landcover subclass of leisure=park

Target = Callable[[dict[str, object], int], str | None]
TilePoint = tuple[int, int]


class TileError(osm.OsmError):
    """A tile, or the tile server, that could not be read; the message says why. An OsmError: the tiles are
    OpenStreetMap's data too, and basemap.street_map reads both failures alike."""


# ---------- Reading a tile (protobuf, MVT 2.1) ----------

def _varint(buf: bytes, pos: int) -> tuple[int, int]:
    byte = buf[pos]
    if byte < 0x80:
        return byte, pos + 1
    result, shift = byte & 0x7F, 7
    while True:
        pos += 1
        byte = buf[pos]
        result |= (byte & 0x7F) << shift
        if byte < 0x80:
            return result, pos + 1
        shift += 7
        if shift > 63:
            raise TileError("a number longer than 64 bits")


def _fields(buf: bytes, start: int, end: int) -> Iterator[tuple[int, int, object]]:
    """A message's fields: (number, wire type, value), the value a number for varints, the (start, end) of the bytes
    for length-delimited fields, and the bytes themselves for fixed-size ones."""
    pos = start
    while pos < end:
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(buf, pos)
            yield number, wire, value
        elif wire == 2:
            length, pos = _varint(buf, pos)
            if pos + length > end:
                raise TileError("a field runs past its message")
            yield number, wire, (pos, pos + length)
            pos += length
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if pos + size > end:
                raise TileError("a field runs past its message")
            yield number, wire, buf[pos:pos + size]
            pos += size
        else:
            raise TileError(f"unknown wire type {wire}")
    if pos != end:
        raise TileError("a message runs past its end")


def _packed(buf: bytes, start: int, end: int) -> list[int]:
    """A packed repeated uint32: tags and geometry."""
    out: list[int] = []
    append = out.append
    value = shift = 0
    for byte in buf[start:end]:
        if byte < 0x80:
            append(value | (byte << shift))
            value = shift = 0
        else:
            value |= (byte & 0x7F) << shift
            shift += 7
    if shift:
        raise TileError("a packed number is cut short")
    return out


def _value(buf: bytes, start: int, end: int) -> object:
    """A layer's tag value: a string, a number or a boolean."""
    for number, wire, value in _fields(buf, start, end):
        if wire == 2 and number == 1:
            first, last = value  # type: ignore[misc]
            return buf[first:last].decode("utf-8", "replace")
        if wire == 5 and number == 2:
            return struct.unpack("<f", value)[0]  # type: ignore[arg-type]
        if wire == 1 and number == 3:
            return struct.unpack("<d", value)[0]  # type: ignore[arg-type]
        if wire == 0 and number == 4:
            return value - (1 << 64) if value >= 1 << 63 else value  # type: ignore[operator]
        if wire == 0 and number == 5:
            return value
        if wire == 0 and number == 6:
            return (value >> 1) ^ -(value & 1)  # type: ignore[operator]
        if wire == 0 and number == 7:
            return bool(value)
    return None


def _layer_name(buf: bytes, start: int, end: int) -> str | None:
    """A layer's name, its first field as encoders write it, so a layer not wanted costs a few bytes to skip."""
    for number, wire, value in _fields(buf, start, end):
        if number == 1 and wire == 2:
            first, last = value  # type: ignore[misc]
            return buf[first:last].decode("utf-8", "replace")
    return None


def _feature(buf: bytes, start: int, end: int) -> tuple[tuple[int, int] | None, int, tuple[int, int] | None]:
    """Where a feature's tags and geometry are, and its geometry type, without decoding either."""
    tags = geometry = None
    kind = 0
    pos = start
    while pos < end:
        key, pos = _varint(buf, pos)
        number, wire = key >> 3, key & 7
        if wire == 2:
            length, pos = _varint(buf, pos)
            if number == 2:
                tags = (pos, pos + length)
            elif number == 4:
                geometry = (pos, pos + length)
            pos += length
        elif wire == 0:
            value, pos = _varint(buf, pos)
            if number == 3:
                kind = value
        elif wire in (1, 5):
            pos += 8 if wire == 1 else 4
        else:
            raise TileError(f"unknown wire type {wire}")
    if pos != end:
        raise TileError("a feature runs past its end")
    return tags, kind, geometry


def _parts(ints: list[int]) -> list[list[TilePoint]]:
    """A geometry's parts in tile coordinates: each MoveTo starts one (a line, or a polygon's ring), each LineTo goes on,
    and a ClosePath closes the ring (its first point repeated)."""
    parts: list[list[TilePoint]] = []
    part: list[TilePoint] | None = None
    x = y = 0
    i, n = 0, len(ints)
    while i < n:
        command = ints[i]
        i += 1
        op, count = command & 7, command >> 3
        if op == 7:
            if part is not None and len(part) >= 3:
                part.append(part[0])
            continue
        if op not in (1, 2) or i + 2 * count > n:
            raise TileError("a geometry command is cut short or unknown")
        for _ in range(count):
            dx, dy = ints[i], ints[i + 1]
            i += 2
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            if op == 1:
                part = [(x, y)]
                parts.append(part)
            elif part is None:
                raise TileError("a line starts without a MoveTo")
            else:
                part.append((x, y))
    return parts


def _read_layer(buf: bytes, start: int, end: int, target: Target) -> list[tuple[str, int, int, list[list[TilePoint]]]]:
    keys: list[str] = []
    values: list[object] = []
    features: list[tuple[int, int]] = []
    extent = 4096
    for number, wire, value in _fields(buf, start, end):
        if wire == 2:
            if number == 2:
                features.append(value)  # type: ignore[arg-type]
            elif number == 3:
                first, last = value  # type: ignore[misc]
                keys.append(buf[first:last].decode("utf-8", "replace"))
            elif number == 4:
                values.append(_value(buf, *value))  # type: ignore[misc]
        elif wire == 0 and number == 5:
            extent = value  # type: ignore[assignment]
    if extent <= 0:
        raise TileError("a layer without an extent")
    wanted = {index: key for index, key in enumerate(keys) if key in KEYS}
    out = []
    for first, last in features:
        tags_at, kind, geometry_at = _feature(buf, first, last)
        tags: dict[str, object] = {}
        if tags_at is not None and wanted:
            ints = _packed(buf, *tags_at)
            for i in range(0, len(ints) - 1, 2):
                key = wanted.get(ints[i])
                if key is not None:
                    tags[key] = values[ints[i + 1]]
        name = target(tags, kind)
        if name is None or geometry_at is None:
            continue
        out.append((name, kind, extent, _parts(_packed(buf, *geometry_at))))
    return out


def read_tile(data: bytes, targets: Mapping[str, Target]) -> list[tuple[str, int, int, list[list[TilePoint]]]]:
    """The features of a tile the map draws: for each layer named in `targets`, those its target names (a street layer,
    "water" or "park", from the feature's tags and geometry type), as (name, geometry type, extent, parts in tile
    coordinates). Other layers are skipped by their length, and a feature no target names by its own."""
    out = []
    try:
        for number, wire, value in _fields(data, 0, len(data)):
            if number != 3 or wire != 2:
                continue
            start, end = value  # type: ignore[misc]
            target = targets.get(_layer_name(data, start, end) or "")
            if target is not None:
                out += _read_layer(data, start, end, target)
    except (IndexError, ValueError, struct.error) as exc:
        raise TileError(f"a tile that cannot be read ({type(exc).__name__})") from None
    return out


def targets(layers: Iterable[str]) -> dict[str, Target]:
    """What the map draws of each layer, for the street layers asked for (basemap.layers_for): their roads, water (the
    big kinds only for a map bigger than a walk) and, for a walk-sized map, parks."""
    wanted = set(layers)
    walk_sized = "residential" in wanted
    water = WALK_WATER if walk_sized else BIG_WATER

    def street(tags: dict[str, object], kind: int) -> str | None:
        if tags.get("ramp") == 1:  # motorway links and other ramps, which the Overpass query leaves out too
            return None
        kind_of = tags.get("class")
        layer = STREET_CLASSES.get(f"{kind_of}/{tags.get('subclass')}" if kind_of == "path" else str(kind_of))
        if layer not in wanted or kind not in (LINE, POLYGON) or (kind == POLYGON and layer != "pedestrian"):
            return None  # a pedestrian square comes as an area and is drawn as its outline, as Overpass gives it
        return layer

    def body_of_water(tags: dict[str, object], kind: int) -> str | None:
        return "water" if kind == POLYGON and tags.get("class") in water else None

    def park(tags: dict[str, object], kind: int) -> str | None:
        return "park" if kind == POLYGON and tags.get("subclass") == PARK else None

    out: dict[str, Target] = {"transportation": street, "water": body_of_water}
    if walk_sized:
        out["landcover"] = park
    return out


# ---------- Tiles and the box ----------

def _edges(box: Box) -> tuple[float, float, float, float]:
    """The box's south, west, north and east in degrees, unrounded."""
    kx = box.kx
    return (box.lat0 + box.south / _M_PER_DEG, box.lon0 + box.west / kx, box.lat0 + box.north / _M_PER_DEG,
            box.lon0 + box.east / kx)


def _tile_x(lon: float, zoom: int) -> int:
    n = 1 << zoom
    return min(n - 1, max(0, math.floor((lon + 180.0) / 360.0 * n)))


def _tile_y(lat: float, zoom: int) -> int:
    n = 1 << zoom
    lat = max(-85.0511, min(85.0511, lat))
    return min(n - 1, max(0, math.floor((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)))


def tile_range(box: Box, zoom: int) -> tuple[int, int, int, int]:
    """The tiles covering the box at `zoom`: the first and last column (west to east) and row (north to south)."""
    south, west, north, east = _edges(box)
    return _tile_x(west, zoom), _tile_y(north, zoom), _tile_x(east, zoom), _tile_y(south, zoom)


def tile_count(box: Box, zoom: int) -> int:
    x0, y0, x1, y1 = tile_range(box, zoom)
    return (x1 - x0 + 1) * (y1 - y0 + 1)


def zoom_for(box: Box, layers: Iterable[str]) -> int:
    """The highest zoom, up to MAX_ZOOM, at which the box needs at most MAX_TILES tiles, but no lower than the zoom that
    first carries the smallest street layer asked for (a 10-minute walk: 14, or 13 for a wide one; the main roads of a
    town: 11 or 12); only a box that would still need more than MOST_TILES goes lower, with fewer roads."""
    floor = max((MIN_ZOOMS[layer] for layer in layers if layer in MIN_ZOOMS), default=MIN_ZOOMS["primary"])
    zoom = MAX_ZOOM
    while zoom > floor and tile_count(box, zoom) > MAX_TILES:
        zoom -= 1
    while zoom > 0 and tile_count(box, zoom) > MOST_TILES:
        zoom -= 1
    return zoom


@dataclass(frozen=True)
class Grid:
    """The world's tiles at a zoom, in a box's metres. Positions are fractions of the world's width and height (Web
    Mercator), the same whichever tile gives them, so tiles that share an edge agree on it to the last bit."""

    box: Box
    zoom: int
    kx: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kx", self.box.kx)

    def x(self, fx: float) -> float:
        return (fx * 360.0 - 180.0 - self.box.lon0) * self.kx

    def y(self, fy: float) -> float:
        return (math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * fy)))) - self.box.lat0) * _M_PER_DEG

    def metres(self, part: list[TilePoint], column: int, row: int, extent: int) -> list[Point]:
        """A part's tile coordinates as metres, through the world's grid; repeated points dropped."""
        world = extent << self.zoom
        ox, oy = column * extent, row * extent
        kx, lon0, lat0 = self.kx, self.box.lon0, self.box.lat0
        sinh, atan, degrees, pi = math.sinh, math.atan, math.degrees, math.pi
        out: list[Point] = []
        last = None
        for x, y in part:
            if (x, y) == last:
                continue
            last = (x, y)
            out.append((((ox + x) / world * 360.0 - 180.0 - lon0) * kx,
                        (degrees(atan(sinh(pi * (1.0 - 2.0 * ((oy + y) / world))))) - lat0) * _M_PER_DEG))
        return out

    def tile(self, column: int, row: int, pad: float = 0.0) -> Box | None:
        """The tile's square in metres, `pad` tile widths past each edge, cut to the box; None when it misses the box."""
        n = 1 << self.zoom
        west, east = self.x(column / n), self.x((column + 1) / n)
        north, south = self.y(row / n), self.y((row + 1) / n)
        px, py = pad * (east - west), pad * (north - south)
        box = self.box
        cut = Box(box.lat0, box.lon0, max(box.west, west - px), max(box.south, south - py), min(box.east, east + px),
                  min(box.north, north + py))
        return cut if cut.west < cut.east and cut.south < cut.north else None


# ---------- Pieces of the map, tile by tile ----------

@dataclass
class Pieces:
    """One tile's part of the map, in metres, cut to the tile (streets) or just past it (water and parks)."""

    streets: dict[str, list[list[Point]]] = field(default_factory=lambda: {layer: [] for layer in basemap.STREET_LAYERS})
    water: list[list[Point]] = field(default_factory=list)
    parks: list[list[Point]] = field(default_factory=list)


def _tile_area(ring: list[TilePoint]) -> int:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False))


def _rings(parts: list[list[TilePoint]]) -> Iterator[tuple[list[TilePoint], bool]]:
    """A polygon's rings and whether each is an outer one: in MVT 2 a polygon's first ring is outer, its holes wind the
    other way, and the next ring winding as the first starts another polygon."""
    first = 0
    for ring in parts:
        if len(ring) < 4 or ring[0] != ring[-1]:
            continue
        area = _tile_area(ring)
        if not area:
            continue
        sign = 1 if area > 0 else -1
        first = first or sign
        yield ring, sign == first


def read_piece(data: bytes, column: int, row: int, grid: Grid, wanted: Mapping[str, Target]) -> Pieces:
    """What tile (column, row) holds of the map, in the grid's metres: street lines cut to the tile, water and park rings
    (counterclockwise around the area, clockwise around a hole) cut OVERLAP units past it."""
    pieces = Pieces()
    lines_box = grid.tile(column, row)
    if lines_box is None or not data:
        return pieces
    areas_box = grid.tile(column, row, OVERLAP / 4096)
    for name, kind, extent, parts in read_tile(data, wanted):
        if name in pieces.streets:
            if kind == LINE:
                for part in parts:
                    line = grid.metres(part, column, row, extent)
                    if len(line) >= 2:
                        pieces.streets[name] += basemap.clip_line(line, lines_box)
            else:  # a pedestrian square: its outline
                for ring, outer in _rings(parts):
                    line = grid.metres(ring, column, row, extent)
                    if outer and len(line) >= 4:
                        pieces.streets[name] += [part for part in basemap.clip_chain(line, lines_box) if len(part) >= 2]
            continue
        rings = pieces.water if name == "water" else pieces.parks
        for ring, outer in _rings(parts):
            area = grid.metres(ring, column, row, extent)
            if len(area) < 4 or areas_box is None:
                continue
            if (basemap.area_m2(area) > 0) != outer:
                area.reverse()
            cut = basemap.clip_area(area, areas_box)
            if len(cut) >= 4:
                rings.append(cut)
    return pieces


def snap_ends(lines: list[list[Point]], edges_x: set[float], edges_y: set[float], within: float = SNAP_M) -> None:
    """Joins the cut ends of streets that go on in the next tile: ends on the same inner tile edge within `within`
    metres of each other become one point (two tiles' copies of a street may differ by a fraction of a unit past the
    edge), so basemap.merged joins the street again."""
    on_edge: dict[tuple[int, float], list[tuple[float, int, int]]] = defaultdict(list)
    for index, line in enumerate(lines):
        for end in (0, -1):
            x, y = line[end]
            if x in edges_x:
                on_edge[(0, x)].append((y, index, end))
            elif y in edges_y:
                on_edge[(1, y)].append((x, index, end))
    for (axis, at), ends in on_edge.items():
        ends.sort()
        anchor = -math.inf
        for along, index, end in ends:
            if along - anchor > within:
                anchor = along
            lines[index][end] = (at, anchor) if axis == 0 else (anchor, at)


def as_of(version: str) -> str | None:
    """The date OpenFreeMap built its tiles, from the version in their address ('20261018_080001_pt')."""
    found = re.search(r"(\d{4})(\d{2})(\d{2})_\d{6}", version)
    return "-".join(found.groups()) if found else None


def assemble(
    pieces: Iterable[Pieces], grid: Grid, tiles: tuple[int, int, int, int], walk: list[Point], layers: tuple[str, ...],
    version: str,
) -> dict:
    """The tiles' pieces as one map, shaped as an Overpass map is (basemap.payload). Raises TileError when they hold no
    street, which an area traced over streets always has."""
    streets: dict[str, list[list[Point]]] = {layer: [] for layer in basemap.STREET_LAYERS}
    water: list[list[Point]] = []
    parks: list[list[Point]] = []
    for piece in pieces:
        for layer, lines in piece.streets.items():
            streets[layer] += lines
        water += piece.water
        parks += piece.parks
    x0, y0, x1, y1 = tiles
    n = 1 << grid.zoom
    edges_x = {grid.x(column / n) for column in range(x0 + 1, x1 + 1)}
    edges_y = {grid.y(row / n) for row in range(y0 + 1, y1 + 1)}
    joined = {}
    for layer, lines in streets.items():
        snap_ends(lines, edges_x, edges_y)
        lines = [[p for i, p in enumerate(line) if i == 0 or p != line[i - 1]] for line in lines]
        joined[layer] = basemap.merged([line for line in lines if len(line) >= 2])
    if not any(joined.values()):
        raise TileError("no streets in the tiles")
    shaped = basemap.payload(basemap.Layers(joined, water, parks), grid.box, walk, layers, credit=CREDIT)
    return {"source": SOURCE, "as_of": as_of(version), "zoom": grid.zoom, "tiles": (x1 - x0 + 1) * (y1 - y0 + 1),
            **shaped}


# ---------- The client ----------

def _saved(path: Path, max_age: float) -> tuple[bytes, float] | None:
    try:
        stamp = path.stat().st_mtime
        if time.time() - stamp >= max_age:
            return None
        return path.read_bytes(), stamp
    except OSError:
        return None


def _describe(exc: BaseException) -> str:
    return str(exc) if isinstance(exc, TileError) else type(exc).__name__


def _tilejson(raw: object) -> dict:
    """What the client needs of OpenFreeMap's TileJSON: the tiles' address, with {z}, {x} and {y}, and their version."""
    if not isinstance(raw, dict) or not isinstance(raw.get("tiles"), list) or not raw["tiles"]:
        raise TileError("a TileJSON without tiles")
    template = str(raw["tiles"][0])
    if not template.startswith("https://") or not all(part in template for part in ("{z}", "{x}", "{y}")):
        raise TileError("a TileJSON with an unexpected tile address")
    found = re.search(r"/planet/([^/]+)/\{z\}", template)
    version = found.group(1) if found else hashlib.sha1(template.encode()).hexdigest()[:12]
    return {"template": template, "version": re.sub(r"[^\w.-]", "_", version),
            "maxzoom": int(raw.get("maxzoom") or MAX_ZOOM)}


class TileClient:
    """Reads OpenFreeMap's vector tiles into the kit's street map (street_map), kept on disk: the TileJSON for a day,
    tiles and shaped maps for a week, under `cache_dir`."""

    def __init__(
        self, cache_dir: Path, url: str = TILEJSON_URL, *, budget: float = BUDGET_S, timeout: float = TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cache_dir = cache_dir
        self._url = url
        self._budget = budget
        self._timeout = timeout
        self._http = httpx.AsyncClient(
            headers={"User-Agent": osm.USER_AGENT}, transport=transport, follow_redirects=True, verify=tls.context(),
        )
        self._gate = asyncio.Semaphore(PARALLEL)
        self._info: tuple[dict, float] | None = None  # the TileJSON read, and until when it is used
        self.downloads = 0
        self.cache_hits = 0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def street_map(self, box: Box, walk: list[Point], layers: Iterable[str] = basemap.STREET_LAYERS) -> dict:
        """The street map of the box (its streets of the layers asked for, water and parks), shaped as basemap.shape
        shapes an Overpass answer, with its source, the date of its data, the zoom and the number of tiles read.
        Raises TileError when the tiles cannot be read within the budget or hold no street."""
        layers = tuple(layer for layer in basemap.STREET_LAYERS if layer in set(layers))
        try:
            async with asyncio.timeout(self._budget):
                return await self._street_map(box, walk, layers)
        except TimeoutError:
            raise TileError(f"the tiles took longer than {self._budget:.0f} s") from None
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, zlib.error) as exc:
            raise TileError(f"the tiles could not be read ({_describe(exc)})") from None

    async def _street_map(self, box: Box, walk: list[Point], layers: tuple[str, ...]) -> dict:
        info = await self._tilejson()
        zoom = min(zoom_for(box, layers), info["maxzoom"])
        key = json.dumps([info["version"], zoom, [box.lat0, box.lon0, box.west, box.south, box.east, box.north], layers])
        cache_file = self._cache_dir / f"map-{hashlib.sha1(key.encode()).hexdigest()}.json"
        saved = _saved(cache_file, MAX_AGE_S)
        if saved is not None:
            self.cache_hits += 1
            return json.loads(saved[0])
        tiles = tile_range(box, zoom)
        x0, y0, x1, y1 = tiles
        grid = Grid(box, zoom)
        wanted = targets(layers)
        missing: list[tuple[int, int]] = []

        async def piece(column: int, row: int) -> Pieces:
            data = await self._tile(info, zoom, column, row)
            if data is None:
                missing.append((column, row))
                return Pieces()
            return await asyncio.to_thread(read_piece, data, column, row, grid, wanted)

        tasks = [asyncio.ensure_future(piece(x, y)) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
        try:
            pieces = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        if missing:  # OpenFreeMap has a tile for every place, the sea's included: a map without one would hide a shore
            if len(missing) == len(tasks):  # it moved on from this version of its tiles: read its TileJSON again
                self._info = None
                (self._cache_dir / "tilejson.json").unlink(missing_ok=True)
                raise TileError("the tiles are gone")
            raise TileError(f"{len(missing)} of {len(tasks)} tiles missing")
        shaped = await asyncio.to_thread(assemble, pieces, grid, tiles, walk, layers, info["version"])
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(shaped, ensure_ascii=False), encoding="utf-8")
        return shaped

    async def _tilejson(self) -> dict:
        if self._info is not None and time.time() < self._info[1]:
            return self._info[0]
        cache_file = self._cache_dir / "tilejson.json"
        saved = _saved(cache_file, math.inf)
        if saved is not None and time.time() - saved[1] < TILEJSON_MAX_AGE_S:
            info = _tilejson(json.loads(saved[0]))
            self._info = (info, saved[1] + TILEJSON_MAX_AGE_S)
            return info
        try:
            response = await self._http.get(self._url, timeout=httpx.Timeout(self._timeout, connect=CONNECT_S))
            if response.status_code != 200:
                raise TileError(f"HTTP {response.status_code} for the TileJSON")
            raw = response.json()
            info = _tilejson(raw)
        except (httpx.HTTPError, ValueError, TileError) as exc:
            if saved is None:
                raise TileError(f"OpenFreeMap's TileJSON could not be read ({_describe(exc)})") from None
            log.warning("OpenFreeMap's TileJSON could not be read (%s); using the one from %s", _describe(exc),
                        time.ctime(saved[1]))
            info = _tilejson(json.loads(saved[0]))
            self._info = (info, time.time() + STALE_RETRY_S)
            return info
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(raw), encoding="utf-8")
        self._info = (info, time.time() + TILEJSON_MAX_AGE_S)
        return info

    async def _tile(self, info: dict, zoom: int, column: int, row: int) -> bytes | None:
        """A tile's protobuf, from the disk or OpenFreeMap; b"" for an empty tile, None for one it does not have."""
        cache_file = self._cache_dir / info["version"] / f"{zoom}-{column}-{row}.pbf"
        saved = _saved(cache_file, MAX_AGE_S)
        if saved is not None:
            self.cache_hits += 1
            return saved[0]
        url = info["template"].replace("{z}", str(zoom)).replace("{x}", str(column)).replace("{y}", str(row))
        problem = "no answer"
        for _ in range(TRIES):
            try:
                async with self._gate:
                    response = await self._http.get(url, timeout=httpx.Timeout(self._timeout, connect=CONNECT_S))
            except httpx.HTTPError as exc:
                problem = _describe(exc)
                continue
            if response.status_code == 404:
                return None
            if response.status_code not in (200, 204):
                problem = f"HTTP {response.status_code}"
                if response.status_code in (408, 429) or response.status_code >= 500:
                    continue
                break
            data = response.content if response.status_code == 200 else b""
            if data[:2] == b"\x1f\x8b":  # gzip the server did not declare, so httpx left it
                data = zlib.decompress(data, 16 + zlib.MAX_WBITS)
            self.downloads += 1
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_bytes(data)
            return data
        raise TileError(f"tile {zoom}/{column}/{row}: {problem}")
