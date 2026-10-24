"""The streets and water around the survey's area, for the kit's two maps: the report's cover and the window poster.

One Overpass query per kit reads, in a box around the area (its bounds plus 60% of its reach, widened for a wide
frame), the streets its size calls for (every street up to 10 km², from motorways down to residential and pedestrian
streets; the main roads to tertiary up to 60 km²; motorways, trunk and primary roads beyond), water (lakes, rivers
drawn as areas, the sea along the coastline) and, for a walk-sized area, parks. It is asked like the survey's
cross-check (app.osm: the same instances, User-Agent, manners and on-disk cache). The answer is clipped to the box,
simplified (Ramer-Douglas-Peucker, a few metres for a walk, harder for a bigger box) and capped at about 2,000 points
(under 60 KB), then kept with the kit, so it is fetched once.

The public Overpass instances often time out or refuse for hours, so they get BUDGET_S seconds in all; then the same
map is read from a second, independent source of the same data: OpenFreeMap's vector tiles (app.vectortiles, up to its
own 30 s), cut to the same box, simplified and capped the same way (payload). Only when neither answers is there no
street map: the maps draw the area and its places without one and say so. No street or shore is ever made up.

Overpass gives an area's edges only where they cross the box, so which side of an edge is water is read from the site:
a storefront stands on land, so a point is water when a line from the site to it crosses that body of water's edges an
odd number of times. A body of water that would then cover most of the area, or whose own rings hold the site, is left
out rather than drawn inverted.

Data © OpenStreetMap contributors, available under the Open Database License (www.openstreetmap.org/copyright).
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from functools import partial
from typing import Protocol

from . import osm
from .catchment import Catchment

log = logging.getLogger("walkin")

MARGIN = 0.6  # of the walk's reach, around its bounds
WIDE = 1.8  # the box is at least this many times as wide as it is tall
MAX_POINTS = 2000
TOLERANCES_M = (2.0, 3.0, 5.0, 8.0, 12.0)  # tried in turn until the map holds at most MAX_POINTS
MIN_AREA_M2 = 400.0  # water or a park smaller than this is a fountain or a lawn, not a landmark
SERVER_TIMEOUT_S = 25
TIMEOUT_S = 35.0  # one request: a city's streets take an instance longer than the cross-check's places
# Every instance asked, together: then the vector tiles (app.vectortiles.BUDGET_S), so the map is ready in about a minute
# at worst, while the kit's copy is written.
BUDGET_S = 40.0
CACHE_NAME = "basemap"
WET_SAMPLE = 64  # outline points tested for water; a drive's outline has hundreds, and each is tested against the coast
_M_PER_DEG = 111_320.0
_EPS = 1e-6

# Street layers, from the roads a city is read by to the streets only people on foot use; each is drawn thinner.
LAYERS = {
    "motorway": "primary", "trunk": "primary", "primary": "primary",
    "secondary": "secondary", "tertiary": "secondary",
    "unclassified": "residential", "residential": "residential", "living_street": "residential",
    "pedestrian": "pedestrian",
}
STREET_LAYERS = ("primary", "secondary", "residential", "pedestrian")
# When the map holds too many points at the coarsest tolerance, these fill what room is left, a group at a time.
THINNED = (("secondary",), ("residential", "pedestrian"))

Point = tuple[float, float]  # metres east and north of the site


@dataclass(frozen=True)
class Box:
    """The map's box around the walk, in metres east and north of the site (an equirectangular projection at its
    latitude, as the maps draw it)."""

    lat0: float
    lon0: float
    west: float
    south: float
    east: float
    north: float

    @property
    def kx(self) -> float:
        return _M_PER_DEG * math.cos(math.radians(self.lat0))

    def metres(self, lat: float, lon: float) -> Point:
        return (lon - self.lon0) * self.kx, (lat - self.lat0) * _M_PER_DEG

    def degrees(self, point: Point) -> list[float]:
        """[lat, lon], as the kit's other shapes are given."""
        x, y = point
        return [round(self.lat0 + y / _M_PER_DEG, 5), round(self.lon0 + x / self.kx, 5)]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """South, west, north, east in degrees, as Overpass reads a bounding box."""
        (south, west), (north, east) = self.degrees((self.west, self.south)), self.degrees((self.east, self.north))
        return south, west, north, east

    def inside(self, point: Point) -> bool:
        x, y = point
        return self.west - _EPS <= x <= self.east + _EPS and self.south - _EPS <= y <= self.north + _EPS


def box_for(catchment: Catchment) -> Box:
    """The walk's bounds plus MARGIN of its reach (the farthest it gets from the site) on every side, widened east and
    west to WIDE times its height, so a wide frame such as the poster's shows streets to its edges."""
    origin = Box(catchment.lat, catchment.lon, 0, 0, 0, 0)
    points = [origin.metres(lat, lon) for lon, lat in catchment.ring]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    margin = MARGIN * max(math.hypot(x, y) for x, y in points)
    middle = (min(xs) + max(xs)) / 2
    half_height = (max(ys) - min(ys)) / 2 + margin
    half_width = max((max(xs) - min(xs)) / 2 + margin, WIDE * half_height)
    return Box(catchment.lat, catchment.lon, middle - half_width, min(ys) - margin, middle + half_width, max(ys) + margin)


def highways(layers: Iterable[str] = STREET_LAYERS) -> str:
    """The highway values of the street layers asked for, as an Overpass regular expression's alternatives."""
    wanted = set(layers)
    return "|".join(kind for kind, layer in LAYERS.items() if layer in wanted)


STREETS = highways()
# The street layers a map of the area draws, by its size (Catchment.area_m2): every street for a walk-sized area, the
# main roads (motorway to tertiary) up to MAIN_ROADS_UP_TO_M2, the arterials (motorway, trunk, primary) beyond.
ALL_STREETS_UP_TO_M2 = 10e6
MAIN_ROADS_UP_TO_M2 = 60e6
MAIN_ROADS = ("primary", "secondary")
ARTERIALS = ("primary",)
# A 10-minute walk's box is 4 to 5 km wide; a bigger box is simplified harder in proportion, so the map keeps its size.
WALK_BOX_M = 5000.0
# The water a map bigger than a walk asks for by its kind (OpenStreetMap's water=*): not the ponds.
BIG_WATER = "river|lake|reservoir|lagoon|canal|oxbow"


def layers_for(catchment: Catchment | None) -> tuple[str, ...]:
    """The street layers a map of the area draws, by the area's size."""
    if catchment is None or len(catchment.ring) < 4:
        return STREET_LAYERS
    area = catchment.area_m2
    if area <= ALL_STREETS_UP_TO_M2:
        return STREET_LAYERS
    return MAIN_ROADS if area <= MAIN_ROADS_UP_TO_M2 else ARTERIALS


def query(box: Box, layers: Iterable[str] = STREET_LAYERS) -> str:
    """One Overpass QL query for the streets of the layers asked for, water, and parks when the map draws every street
    (an area larger than a walk shows its main roads, and its parks would be specks), all in the box, their geometry
    cut to it (Overpass keeps the first node outside it at each end and leaves the rest null), so a river's thousands
    of nodes stay at home."""
    layers = tuple(layers)
    area = "({:.5f},{:.5f},{:.5f},{:.5f})".format(*box.bbox)
    walk_sized = "residential" in layers
    wanted = [f'way["highway"~"^({highways(layers)})$"]']
    if walk_sized:
        wanted += ['way["natural"~"^(water|coastline)$"]', 'way["leisure"="park"]', 'rel["leisure"="park"]']
    else:  # a region's ponds would outnumber its roads: its rivers, lakes and coast only
        wanted += ['way["natural"="coastline"]', f'way["natural"="water"]["water"~"^({BIG_WATER})$"]']
    wanted += ['way["waterway"="riverbank"]', 'rel["natural"="water"]', 'rel["waterway"="riverbank"]']
    each = "".join(f"{statement}{area};" for statement in wanted)
    return f"[out:json][timeout:{SERVER_TIMEOUT_S}][maxsize:{osm.SERVER_MAXSIZE}];({each});out geom{area} qt;"


# ---------- Reading the answer ----------

def is_water(tags: dict) -> bool:
    return tags.get("natural") == "water" or tags.get("waterway") == "riverbank"


def runs_of(geometry: Iterable[dict | None] | None, box: Box) -> list[list[Point]]:
    """A way's geometry as the stretches Overpass gave, in metres: it leaves null the nodes outside the box but the
    first one at each end, so each stretch still crosses the box's edge."""
    runs: list[list[Point]] = []
    run: list[Point] = []
    for node in geometry or []:
        if node is None:
            if len(run) >= 2:
                runs.append(run)
            run = []
            continue
        point = box.metres(float(node["lat"]), float(node["lon"]))
        if not run or point != run[-1]:
            run.append(point)
    if len(run) >= 2:
        runs.append(run)
    return runs


def chains_of(runs: Iterable[list[Point]]) -> list[list[Point]]:
    """Stretches joined end to end wherever they share a node, whichever way each runs; a ring comes back closed."""
    pieces = [list(run) for run in runs if len(run) >= 2]
    ends: dict[Point, list[int]] = defaultdict(list)
    for index, piece in enumerate(pieces):
        ends[piece[0]].append(index)
        ends[piece[-1]].append(index)
    used: set[int] = set()
    chains = []
    for index, piece in enumerate(pieces):
        if index in used:
            continue
        used.add(index)
        chain = piece[:]
        while chain[0] != chain[-1]:
            following = next((j for j in ends[chain[-1]] if j not in used), None)
            if following is None:
                break
            used.add(following)
            other = pieces[following]
            chain += other[1:] if other[0] == chain[-1] else other[-2::-1]
        while chain[0] != chain[-1]:
            leading = next((j for j in ends[chain[0]] if j not in used), None)
            if leading is None:
                break
            used.add(leading)
            other = pieces[leading]
            chain = (other[:-1] if other[-1] == chain[0] else other[:0:-1]) + chain
        chains.append(chain)
    return chains


# ---------- Clipping to the box ----------

def _clip_segment(a: Point, b: Point, box: Box) -> tuple[Point, Point, bool, bool] | None:
    """Liang-Barsky: the part of a-b inside the box, and whether each end was cut (then it lies on the box's edge,
    snapped exactly onto it)."""
    (x1, y1), (x2, y2) = a, b
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    edge0 = edge1 = None
    for p, q, edge in ((-dx, x1 - box.west, "w"), (dx, box.east - x1, "e"), (-dy, y1 - box.south, "s"),
                       (dy, box.north - y1, "n")):
        if abs(p) < 1e-12:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            if t > t0:
                t0, edge0 = t, edge
        else:
            if t < t0:
                return None
            if t < t1:
                t1, edge1 = t, edge
    start = _snap((x1 + t0 * dx, y1 + t0 * dy), edge0, box) if edge0 else a
    end = _snap((x1 + t1 * dx, y1 + t1 * dy), edge1, box) if edge1 else b
    return start, end, edge0 is not None, edge1 is not None


def _snap(point: Point, edge: str, box: Box) -> Point:
    x, y = point
    if edge == "w":
        return box.west, min(max(y, box.south), box.north)
    if edge == "e":
        return box.east, min(max(y, box.south), box.north)
    if edge == "s":
        return min(max(x, box.west), box.east), box.south
    return min(max(x, box.west), box.east), box.north


def clip_line(line: list[Point], box: Box) -> list[list[Point]]:
    """The parts of a line inside the box."""
    parts: list[list[Point]] = []
    current: list[Point] = []
    for a, b in zip(line, line[1:], strict=False):
        cut = _clip_segment(a, b, box)
        if cut is None:
            if len(current) >= 2:
                parts.append(current)
            current = []
            continue
        start, end, entered, left = cut
        if entered or not current:
            if len(current) >= 2:
                parts.append(current)
            current = [start]
        if end != current[-1]:
            current.append(end)
        if left:
            if len(current) >= 2:
                parts.append(current)
            current = []
    if len(current) >= 2:
        parts.append(current)
    return parts


def on_edge(point: Point, box: Box) -> bool:
    x, y = point
    return min(abs(x - box.west), abs(x - box.east), abs(y - box.south), abs(y - box.north)) < 1e-6


# ---------- Areas ----------

def area_m2(ring: list[Point]) -> float:
    """Signed: positive when the ring runs counterclockwise."""
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False)) / 2


def _side(a: Point, b: Point, p: Point) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _crosses(s: Point, t: Point, p: Point, q: Point) -> bool:
    """Whether segment s-t crosses segment p-q; a node exactly on the line s-t counts on one side only, so a line
    through a node of an edge is counted once."""
    if (_side(s, t, p) > 0) == (_side(s, t, q) > 0):
        return False
    return (_side(p, q, s) > 0) != (_side(p, q, t) > 0)


def crossings(s: Point, t: Point, edges: list[list[Point]]) -> int:
    return sum(_crosses(s, t, p, q) for line in edges for p, q in zip(line, line[1:], strict=False))


def _probe(line: list[Point], box: Box) -> Point:
    """A point just to the right of the line's longest segment, inside the box."""
    a, b = max(zip(line, line[1:], strict=False), key=lambda ab: math.dist(*ab))
    length = math.dist(a, b) or 1.0
    x = (a[0] + b[0]) / 2 + 0.5 * (b[1] - a[1]) / length
    y = (a[1] + b[1]) / 2 - 0.5 * (b[0] - a[0]) / length
    return min(max(x, box.west), box.east), min(max(y, box.south), box.north)


def _perimeter(point: Point, box: Box) -> float:
    """Where a point on the box's edge lies along it, counterclockwise from the south-west corner."""
    x, y = point
    width, height = box.east - box.west, box.north - box.south
    if abs(y - box.south) < 1e-6:
        return x - box.west
    if abs(x - box.east) < 1e-6:
        return width + y - box.south
    if abs(y - box.north) < 1e-6:
        return width + height + box.east - x
    return 2 * width + height + box.north - y


def _corners(box: Box) -> list[tuple[float, Point]]:
    width, height = box.east - box.west, box.north - box.south
    return [(0.0, (box.west, box.south)), (width, (box.east, box.south)), (width + height, (box.east, box.north)),
            (2 * width + height, (box.west, box.north))]


def water_rings(edges: list[list[Point]], box: Box, land: Point = (0.0, 0.0)) -> list[list[Point]] | None:
    """One body of water's edges inside the box (chains: rings, or lines from edge to edge of the box) as closed rings
    with the water on their left: counterclockwise around water, clockwise around its islands. Which side of an edge is
    water is read from `land`: a point is water when the line from `land` to it crosses the edges an odd number of
    times. None when the edges do not close up (an edge stops inside the box)."""
    rings, pieces = [], []
    for chain in edges:
        if chain[0] == chain[-1] and len(chain) >= 4:
            rings.append(chain)
        elif on_edge(chain[0], box) and on_edge(chain[-1], box):
            pieces.append(chain)
        else:
            return None
    oriented = []
    for line in rings + pieces:
        water_right = crossings(land, _probe(line, box), edges) % 2 == 1
        oriented.append(line[::-1] if water_right else line)
    rings, pieces = oriented[:len(rings)], oriented[len(rings):]
    if not pieces:
        corner = (box.west, box.south)
        if crossings(land, corner, edges) % 2 == 1:
            rings.append([corner, (box.east, box.south), (box.east, box.north), (box.west, box.north), corner])
        return rings
    total = 2 * (box.east - box.west + box.north - box.south)
    starts = [_perimeter(piece[0], box) for piece in pieces]
    used: set[int] = set()
    for first in range(len(pieces)):
        if first in used:
            continue
        ring: list[Point] = []
        index = first
        while True:
            used.add(index)
            ring += pieces[index]
            at = _perimeter(pieces[index][-1], box)
            index = min(range(len(pieces)), key=lambda j: (starts[j] - at) % total)
            gap = (starts[index] - at) % total
            ring += [corner for position, corner in sorted(_corners(box), key=lambda c: (c[0] - at) % total)
                     if 0 < (position - at) % total < gap]
            if index == first:
                break
            if index in used:
                return None
        rings.append(ring + [ring[0]])
    return rings


def clip_chain(chain: list[Point], box: Box) -> list[list[Point]]:
    """A ring or line's parts inside the box; a ring wholly inside stays closed."""
    if chain[0] == chain[-1] and all(box.inside(p) for p in chain):
        return [chain]
    if chain[0] == chain[-1]:
        # Start the ring outside the box, so no part of it is split at the start.
        outside = next((i for i, p in enumerate(chain) if not box.inside(p)), 0)
        chain = chain[outside:-1] + chain[:outside + 1]
    return clip_line(chain, box)


def clip_area(ring: list[Point], box: Box) -> list[Point]:
    """The part of an area's closed ring inside the box (Sutherland-Hodgman), closed and winding as the ring did; []
    when none of it is. An area the box cuts in several parts comes back as one ring, the parts joined along the box's
    edge by lines of no width, which fill nothing (the maps fill areas and draw no outline)."""
    points = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else list(ring)
    for axis, limit, above in ((0, box.west, True), (0, box.east, False), (1, box.south, True), (1, box.north, False)):
        if not points:
            return []
        kept: list[Point] = []
        previous = points[-1]
        was_in = previous[axis] >= limit if above else previous[axis] <= limit
        for point in points:
            is_in = point[axis] >= limit if above else point[axis] <= limit
            if is_in != was_in:
                t = (limit - previous[axis]) / (point[axis] - previous[axis])
                other = 1 - axis
                cut = previous[other] + t * (point[other] - previous[other])
                kept.append((limit, cut) if axis == 0 else (cut, limit))
            if is_in:
                kept.append(point)
            previous, was_in = point, is_in
        points = kept
    points = [p for i, p in enumerate(points) if p != points[i - 1]]
    return points + [points[0]] if len(points) >= 3 else []


def winding(point: Point, rings: Iterable[list[Point]]) -> int:
    """The nonzero rule's winding number of the rings around a point."""
    x, y = point
    total = 0
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
            if y1 <= y < y2 and _side((x1, y1), (x2, y2), point) > 0:
                total += 1
            elif y2 <= y < y1 and _side((x1, y1), (x2, y2), point) < 0:
                total -= 1
    return total


def body_of_water(members: list[tuple[str, list[list[Point]]]], box: Box, walk: list[Point]) -> list[list[Point]]:
    """A body of water's rings inside the box, from its members' stretches by role ('outer', 'inner'; 'coast' for the
    coastline). None when its edges do not close up, when its own closed rings put the site in the water, or when it
    would cover most of the walk, which stands on land: the site's point would read the sides wrong."""
    runs = [run for _, member_runs in members for run in member_runs]
    edges = [part for chain in chains_of(runs) for part in clip_chain(chain, box) if len(part) >= 2]
    if not edges or site_in_water(members):
        return []
    rings = water_rings(edges, box)
    if not rings:
        return []
    # A sample of the outline tells as well as every point, and keeps a big drive's outline cheap against a long coast.
    sample = walk[::max(1, len(walk) // WET_SAMPLE)]
    wet = sum(1 for point in sample if winding(point, rings) != 0)
    return rings if wet <= len(sample) // 2 else []


def site_in_water(members: list[tuple[str, list[list[Point]]]]) -> bool:
    """Whether the body's whole rings, as OpenStreetMap tags them (outer rings water, inner rings islands), hold the
    site, at (0, 0)."""
    depth = 0
    for role, sign in (("outer", 1), ("inner", -1)):
        runs = [run for member_role, member_runs in members if member_role == role for run in member_runs]
        for chain in chains_of(runs):
            if len(chain) >= 4 and chain[0] == chain[-1] and winding((0.0, 0.0), [chain]) != 0:
                depth += sign
    return depth > 0


def park_rings(members: list[tuple[str, list[list[Point]]]], box: Box) -> list[list[Point]]:
    """A park's rings wholly inside the box, outer ones counterclockwise and inner ones clockwise; a park the box cuts
    is left out (unlike water, nothing says which side of a cut edge is the park)."""
    out = []
    for role in ("outer", "inner"):
        runs = [run for member_role, member_runs in members if member_role == role for run in member_runs]
        for chain in chains_of(runs):
            if len(chain) < 4 or chain[0] != chain[-1] or not all(box.inside(p) for p in chain):
                continue
            if (area_m2(chain) > 0) != (role == "outer"):
                chain = chain[::-1]
            out.append(chain)
    return out


# ---------- Simplifying ----------

STRAIGHT_DEG = 30.0  # where several streets of a layer end at one node, two ends this close to head-on are one street


def _inward(line: list[Point], end: int) -> Point:
    (x1, y1), (x2, y2) = (line[0], line[1]) if end == 0 else (line[-1], line[-2])
    return x2 - x1, y2 - y1


def _bend(lines: list[list[Point]], a: tuple[int, int], b: tuple[int, int]) -> float:
    """How far from head-on two line ends meet, in degrees: 0 when one goes straight on as the other."""
    (ax, ay), (bx, by) = _inward(lines[a[0]], a[1]), _inward(lines[b[0]], b[1])
    norm = math.hypot(ax, ay) * math.hypot(bx, by)
    if not norm:
        return 180.0
    return 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, (ax * bx + ay * by) / norm))))


def merged(lines: list[list[Point]]) -> list[list[Point]]:
    """A layer's lines joined where a street goes on as another way: at a node where two ends meet, or where more do,
    pairing the ends that meet most nearly head-on (within STRAIGHT_DEG), so a street split block by block draws as one
    line and simplifies to its corners."""
    lines = [line for line in lines if len(line) >= 2]
    ends: dict[Point, list[tuple[int, int]]] = defaultdict(list)
    for index, line in enumerate(lines):
        ends[line[0]].append((index, 0))
        ends[line[-1]].append((index, 1))
    partner: dict[tuple[int, int], tuple[int, int]] = {}
    for meeting in ends.values():
        free = list(meeting)
        while len(free) >= 2:
            pairs = [(_bend(lines, a, b), a, b) for i, a in enumerate(free) for b in free[i + 1:] if a[0] != b[0]]
            if not pairs:
                break
            bend, a, b = min(pairs)
            if len(meeting) > 2 and bend > STRAIGHT_DEG:
                break
            partner[a], partner[b] = b, a
            free.remove(a)
            free.remove(b)
    out: list[list[Point]] = []
    used: set[int] = set()
    for index in range(len(lines)):
        if index in used:
            continue
        line, end, seen = index, 0, {index}
        while (line, end) in partner:  # back to the first line of the street
            other, other_end = partner[(line, end)]
            if other in seen:
                break
            seen.add(other)
            line, end = other, 1 - other_end
        chain: list[Point] = []
        while True:
            used.add(line)
            points = lines[line] if end == 0 else lines[line][::-1]
            chain += points if not chain else points[1:]
            following = partner.get((line, 1 - end))
            if following is None or following[0] in used:
                break
            line, end = following
        out.append(chain)
    return out


def simplify(line: list[Point], tolerance: float) -> list[Point]:
    """Ramer-Douglas-Peucker in metres; a ring keeps its first point and stays closed."""
    if len(line) <= 2:
        return line
    keep = {0, len(line) - 1}
    stack = [(0, len(line) - 1)]
    while stack:
        first, last = stack.pop()
        a, b = line[first], line[last]
        length = math.dist(a, b)
        best, index = 0.0, None
        for i in range(first + 1, last):
            gap = abs(_side(a, b, line[i])) / length if length else math.dist(a, line[i])
            if gap > best:
                best, index = gap, i
        if index is not None and best > tolerance:
            keep.add(index)
            stack += [(first, index), (index, last)]
    return [line[i] for i in sorted(keep)]


@dataclass
class Layers:
    """The map in metres: street lines by layer, water and park rings."""

    streets: dict[str, list[list[Point]]]
    water: list[list[Point]]
    parks: list[list[Point]]

    def simplified(self, tolerance: float, smallest: float = MIN_AREA_M2) -> Layers:
        """Every line and ring simplified to `tolerance` metres; water and parks smaller than `smallest` m² left out."""
        streets = {layer: lines_of(lines, tolerance) for layer, lines in self.streets.items()}
        return Layers(streets, rings(self.water, tolerance, smallest), rings(self.parks, tolerance, smallest))

    @property
    def points(self) -> int:
        return (sum(len(line) for lines in self.streets.values() for line in lines)
                + sum(len(ring) for ring in self.water) + sum(len(ring) for ring in self.parks))


def lines_of(shapes: list[list[Point]], tolerance: float) -> list[list[Point]]:
    simple = (simplify(line, tolerance) for line in shapes)
    return [line for line in simple if len(line) >= 2]


def rings(shapes: list[list[Point]], tolerance: float, smallest: float = MIN_AREA_M2) -> list[list[Point]]:
    out = []
    for ring in shapes:
        simple = simplify(ring, tolerance)
        if len(simple) >= 4 and abs(area_m2(simple)) >= smallest:
            out.append(simple)
    return out


def fitted(
    layers: Layers, focus: Point | None = None, reach: float = 0.0, scale: float = 1.0,
) -> tuple[Layers, float, list[str], list[str]]:
    """The layers simplified until they hold at most MAX_POINTS, with tolerances and the smallest water or park kept
    grown by `scale` (a box `scale` times a walk's is drawn `scale` times smaller). When even the coarsest tolerance
    holds more (a dense old city), the lesser streets are thinned (thin); when the arterials and the water alone hold
    more (a big drive), the tolerance doubles until they fit. Returns the layers, the tolerance, the layers left out
    whole, and those thinned."""
    smallest = MIN_AREA_M2 * scale * scale
    tolerances = [tolerance * scale for tolerance in TOLERANCES_M]
    for tolerance in tolerances:
        simple = layers.simplified(tolerance, smallest)
        if simple.points <= MAX_POINTS:
            return simple, round(tolerance, 1), [], []
    tolerance = tolerances[-1]
    while True:
        kept, dropped, thinned = thin(layers.simplified(tolerance, smallest), focus, reach)
        if kept.points <= MAX_POINTS or tolerance >= tolerances[-1] * 2 ** 8:
            return kept, round(tolerance, 1), dropped, thinned
        tolerance *= 2


def thin(simple: Layers, focus: Point | None, reach: float) -> tuple[Layers, list[str], list[str]]:
    """The main roads and the water stay, parks while there is room, then the lesser streets fill what is left, a
    layer at a time (THINNED): longest first, those within `reach` of `focus` (the area) counting double, so the map
    keeps the streets that shape it."""
    lesser = {layer for group in THINNED for layer in group}
    room = MAX_POINTS - sum(len(line) for layer, lines in simple.streets.items() if layer not in lesser for line in lines)
    room -= sum(len(ring) for ring in simple.water)
    parks = simple.parks
    dropped: list[str] = []
    if parks and sum(len(ring) for ring in parks) > room:
        parks, dropped = [], ["parks"]
    room -= sum(len(ring) for ring in parks)
    streets = dict(simple.streets)
    thinned: list[str] = []
    for group in THINNED:
        candidates = [(layer, index, line) for layer in group for index, line in enumerate(simple.streets[layer])]
        candidates.sort(key=lambda item: -_weight(item[2], focus, reach))
        kept: dict[str, list[tuple[int, list[Point]]]] = {layer: [] for layer in group}
        for layer, index, line in candidates:
            if len(line) <= room:
                kept[layer].append((index, line))
                room -= len(line)
        for layer in group:
            streets[layer] = [line for _, line in sorted(kept[layer], key=lambda item: item[0])]
            if len(streets[layer]) < len(simple.streets[layer]):
                (thinned if streets[layer] else dropped).append(layer)
    return Layers(streets, simple.water, parks), dropped, thinned


def _weight(line: list[Point], focus: Point | None, reach: float) -> float:
    length = sum(math.dist(a, b) for a, b in zip(line, line[1:], strict=False))
    near = focus is not None and any(math.dist(point, focus) <= reach for point in line)
    return length * (2 if near else 1)


# ---------- The street map ----------

def read(data: dict, box: Box, walk: list[Point], layers: Iterable[str] = STREET_LAYERS) -> Layers:
    """The answer's streets of the layers asked for, water and parks, cut to the box; `walk` is the area's outline."""
    wanted = set(layers)
    streets: dict[str, list[list[Point]]] = {layer: [] for layer in STREET_LAYERS}
    water: list[list[Point]] = []
    coast: list[list[Point]] = []
    parks: list[list[Point]] = []
    for element in data.get("elements") or []:
        tags = element.get("tags") or {}
        if element.get("type") == "way":
            runs = runs_of(element.get("geometry"), box)
            layer = LAYERS.get(tags.get("highway", ""))
            if layer:
                if layer in wanted:
                    streets[layer] += [part for run in runs for part in clip_line(run, box)]
            elif tags.get("natural") == "coastline":
                coast += runs
            elif is_water(tags):
                water += body_of_water([("outer", runs)], box, walk)
            elif tags.get("leisure") == "park":
                parks += park_rings([("outer", runs)], box)
        elif element.get("type") == "relation":
            members = [((m.get("role") or "outer"), runs_of(m.get("geometry"), box))
                       for m in element.get("members") or [] if m.get("type") == "way"]
            if is_water(tags):
                water += body_of_water(members, box, walk)
            elif tags.get("leisure") == "park":
                parks += park_rings(members, box)
    # Every coastline way in the box makes one edge: land on one side, the sea on the other.
    water += body_of_water([("coast", coast)], box, walk)
    return Layers({layer: merged(lines) for layer, lines in streets.items()}, water, parks)


def shape(data: dict, box: Box, walk: list[Point], layers: Iterable[str] = STREET_LAYERS) -> dict:
    """What a kit keeps of an Overpass answer (payload). Raises OsmError when the answer holds no street, which an area
    traced over streets always has."""
    layers = tuple(layers)
    read_layers = read(data, box, walk, layers)
    if not any(read_layers.streets.values()):
        raise osm.OsmError("no streets in the answer")
    return payload(read_layers, box, walk, layers)


def payload(
    read_layers: Layers, box: Box, walk: list[Point], layers: Iterable[str] = STREET_LAYERS, credit: str = osm.CREDIT,
) -> dict:
    """What a kit keeps of a street map read in metres, from an Overpass answer or from vector tiles: [lat, lon] lines
    and rings simplified until they hold at most about MAX_POINTS points (fitted), and the credit its source asks for."""
    layers = tuple(layers)
    xs, ys = [x for x, _ in walk] or [0.0], [y for _, y in walk] or [0.0]
    focus = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    reach = max([math.dist(point, focus) for point in walk] or [0.0])
    scale = max(1.0, (box.east - box.west) / WALK_BOX_M)
    simple, tolerance, dropped, thinned = fitted(read_layers, focus, reach, scale)
    south, west, north, east = box.bbox
    return {
        "box": [[south, west], [north, east]],
        "layers": [layer for layer in STREET_LAYERS if layer in layers],
        "streets": {layer: [[box.degrees(p) for p in line] for line in lines] for layer, lines in simple.streets.items()},
        "water": [[box.degrees(p) for p in ring] for ring in simple.water],
        "parks": [[box.degrees(p) for p in ring] for ring in simple.parks],
        "points": simple.points,
        "tolerance_m": tolerance,
        "dropped": dropped,
        "thinned": thinned,
        "credit": credit,
    }


class TileSource(Protocol):
    """The street map's second source (app.vectortiles.TileClient): the map of a box, shaped as payload shapes it, with
    its "source"; raises when it cannot be read."""

    async def street_map(self, box: Box, walk: list[Point], layers: Iterable[str]) -> dict: ...


async def _from_overpass(client: osm.OsmClient, box: Box, walk: list[Point], layers: tuple[str, ...]) -> dict:
    return await client.ask(query(box, layers), partial(shape, box=box, walk=walk, layers=layers), name=CACHE_NAME,
                            timeout=TIMEOUT_S, budget=BUDGET_S)


async def street_map(
    client: osm.OsmClient | None, catchment: Catchment | None, layers: Iterable[str] = STREET_LAYERS,
    tiles: TileSource | None = None, *, tiles_first: bool = False,
) -> dict | None:
    """The streets of the layers asked for (layers_for: every street for a walk, the main roads for a bigger area),
    water and parks around the survey's area, as the kit keeps them: from Overpass (`client`, BUDGET_S seconds in all),
    else from the vector tiles (`tiles`, app.vectortiles); `tiles_first` asks the tiles first, as opening a kit saved
    without a street map does (they answer in seconds). None when there is no area, or no source is given or answers.
    Never raises: the kit is built without a street map then."""
    sources: list[tuple[str, Callable[[Box, list[Point], tuple[str, ...]], Awaitable[dict]]]] = []
    if client is not None:
        sources.append(("OpenStreetMap's Overpass servers", partial(_from_overpass, client)))
    if tiles is not None:
        sources.append(("OpenFreeMap's vector tiles", tiles.street_map))
    if tiles_first:
        sources.reverse()
    try:
        if catchment is None or len(catchment.ring) < 4:
            return None
        layers = tuple(layer for layer in STREET_LAYERS if layer in set(layers))
        box = box_for(catchment)
        walk = [box.metres(lat, lon) for lon, lat in catchment.ring]
    except Exception:  # an area shaped unlike any seen so far must not stop the kit
        log.warning("No box for the street map", exc_info=True)
        return None
    for name, fetch in sources:
        try:
            return await fetch(box, walk, layers)
        except osm.OsmError as exc:
            log.warning("No street map from %s: %s", name, exc)
        except Exception:  # an answer shaped unlike any seen so far must not stop the kit
            log.warning("The street map from %s failed", name, exc_info=True)
    return None
