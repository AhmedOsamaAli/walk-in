/* The kit's maps laid out in a frame: the street map around the survey's area (app/basemap.py), the area, the site, the
   report's numbered pins and the trips people here make now, as flags at the frame's edge when they fall off it. The
   frame is fitted to the area's bounds, whatever its size. Pure, so it is tested without a browser;
   components/kit/SiteMap.tsx draws the result. */
import type { CoverMap, MapPin, PosterMap, PosterTrip, StreetLayer, StreetMap } from "../api/sitemap";
import type { LatLon } from "../api/types";

const METRES_PER_DEGREE = 111_320;

export const STREET_LAYERS: readonly StreetLayer[] = ["pedestrian", "residential", "secondary", "primary"];

/** Metres east and north of the site: an equirectangular projection at its latitude, as app/basemap.py cuts its box. */
export function localMetres(site: LatLon): (point: LatLon) => [number, number] {
  const [lat0, lon0] = site;
  const kx = METRES_PER_DEGREE * Math.cos((lat0 * Math.PI) / 180);
  return ([lat, lon]) => [(lon - lon0) * kx, (lat - lat0) * METRES_PER_DEGREE];
}

/** A frame's projection: north up, `scale` frame units per metre. */
export interface Frame {
  width: number;
  height: number;
  scale: number;
  at: (point: LatLon) => [number, number];
  site: [number, number];
}

export interface FitOptions {
  width: number;
  height: number;
  /** Room kept around the walk on every side, in frame units. */
  pad: number;
  /** Where the street data stops: the frame slides toward it as far as the walk stays in view. */
  box?: [LatLon, LatLon] | null;
}

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high);
const tenth = (value: number) => Math.round(value * 10) / 10;

/** The view's centre on one axis: the walk (with its pad) always in view, and as little beyond the data as that allows. */
function settle(centre: number, half: number, walk: [number, number], pad: number, data: [number, number] | null): number {
  const walkLow = walk[1] + pad - half;
  const walkHigh = walk[0] - pad + half;
  if (!data) return centre;
  const low = Math.max(walkLow, data[0] + half);
  const high = Math.min(walkHigh, data[1] - half);
  if (low <= high) return clamp(centre, low, high);
  return clamp((data[0] + data[1]) / 2, Math.min(walkLow, walkHigh), Math.max(walkLow, walkHigh));
}

/** The walk ([lat, lon] ring) and the site fitted to a frame, keeping the walk's true proportions. */
export function fitFrame(ring: LatLon[], site: LatLon, options: FitOptions): Frame {
  const { width, height, pad } = options;
  const toLocal = localMetres(site);
  const points = [...ring, site].map(toLocal);
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = Math.min((width - 2 * pad) / Math.max(maxX - minX, 1), (height - 2 * pad) / Math.max(maxY - minY, 1));
  const [halfW, halfH, padM] = [width / 2 / scale, height / 2 / scale, pad / scale];
  let data: { x: [number, number]; y: [number, number] } | null = null;
  if (options.box) {
    const [west, south] = toLocal(options.box[0]);
    const [east, north] = toLocal(options.box[1]);
    data = { x: [west, east], y: [south, north] };
  }
  const centreX = settle((minX + maxX) / 2, halfW, [minX, maxX], padM, data ? data.x : null);
  const centreY = settle((minY + maxY) / 2, halfH, [minY, maxY], padM, data ? data.y : null);
  const at = (point: LatLon): [number, number] => {
    const [x, y] = toLocal(point);
    return [tenth(width / 2 + (x - centreX) * scale), tenth(height / 2 - (y - centreY) * scale)];
  };
  return { width, height, scale, at, site: at(site) };
}

/** Lines as one SVG path. */
export function linePath(lines: LatLon[][], at: Frame["at"]): string {
  return lines
    .filter((line) => line.length >= 2)
    .map((line) => `M${line.map((point) => at(point).join(" ")).join("L")}`)
    .join("");
}

/** Rings as one SVG path, each closed. */
export function ringPath(rings: LatLon[][], at: Frame["at"]): string {
  return rings
    .filter((ring) => ring.length >= 3)
    .map((ring) => `M${ring.map((point) => at(point).join(" ")).join("L")}Z`)
    .join("");
}

/** Where the street data stops, in the frame, when the frame shows beyond it; null when the data fills the frame. */
export function dataEdge(frame: Frame, box: [LatLon, LatLon]): { x: number; y: number; width: number; height: number } | null {
  const [x0, y1] = frame.at(box[0]);
  const [x1, y0] = frame.at(box[1]);
  if (x0 <= 0.5 && y0 <= 0.5 && x1 >= frame.width - 0.5 && y1 >= frame.height - 0.5) return null;
  return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
}

// ---------- Pins ----------

export interface PinMark {
  /** The survey's number for the place; null for a dot. */
  n: number | null;
  name: string;
  main: boolean;
  numbered: boolean;
  /** Where the pin is drawn: moved off its neighbours when they would overlap. */
  x: number;
  y: number;
  /** Where the place is. */
  home: [number, number];
}

/** The pins in the frame. Numbered pins that would overlap each other or the site's mark are eased apart (a leader
    line then joins each to its place); dots stay where their places are. */
export function placePins(pins: MapPin[], frame: Frame, radius: number): PinMark[] {
  const marks: PinMark[] = pins.map((pin) => {
    const home = frame.at([pin.lat, pin.lon]);
    return { n: pin.n, name: pin.name, main: pin.main, numbered: pin.n !== null, x: home[0], y: home[1], home };
  });
  const moving = marks.filter((mark) => mark.numbered);
  const gap = radius * 2 + 1.5;
  const [sx, sy] = frame.site;
  for (let round = 0; round < 80; round += 1) {
    for (let i = 0; i < moving.length; i += 1) {
      const a = moving[i];
      if (!a) continue;
      for (let j = i + 1; j < moving.length; j += 1) {
        const b = moving[j];
        if (!b) continue;
        let [dx, dy] = [b.x - a.x, b.y - a.y];
        let distance = Math.hypot(dx, dy);
        if (distance >= gap) continue;
        if (distance < 1e-3) {
          // Places at one spot part along a fixed angle per pair, so the layout is the same every time.
          const angle = (i * 2.399963 + j) % (2 * Math.PI);
          [dx, dy, distance] = [Math.cos(angle), Math.sin(angle), 1];
        }
        const push = (gap - distance) / 2;
        a.x -= (dx / distance) * push;
        a.y -= (dy / distance) * push;
        b.x += (dx / distance) * push;
        b.y += (dy / distance) * push;
      }
      // The site's mark is no place to put a pin.
      const [ex, ey] = [a.x - sx, a.y - sy];
      const away = Math.hypot(ex, ey);
      const clear = radius + 11;
      if (away < clear) {
        const [ux, uy] = away < 1e-3 ? [0, -1] : [ex / away, ey / away];
        a.x = sx + ux * clear;
        a.y = sy + uy * clear;
      }
    }
    for (const mark of moving) {
      mark.x += (mark.home[0] - mark.x) * 0.04;
      mark.y += (mark.home[1] - mark.y) * 0.04;
      mark.x = clamp(mark.x, radius + 2, frame.width - radius - 2);
      mark.y = clamp(mark.y, radius + 2, frame.height - radius - 2);
    }
  }
  for (const mark of moving) {
    mark.x = tenth(mark.x);
    mark.y = tenth(mark.y);
  }
  return marks;
}

/** The survey's number for each row of the report's competition table: the pins are its rows that have a location
    (a distance), in its order, so the two are read side by side; a row whose pin does not match gets none. */
export function tableNumbers(places: { name: string; distance_m: number | null }[], pins: MapPin[]): (number | null)[] {
  let next = 0;
  return places.map((place) => {
    if (place.distance_m == null) return null;
    const pin = pins[next];
    next += 1;
    return pin?.name === place.name ? pin.n : null;
  });
}

// ---------- Trips ----------

/** A trip as the frame draws it: where the place is, its letter (the report's) and its distance. */
export interface TripInput {
  key: string | null;
  km: number;
  point: LatLon;
}

/** A trip whose place is inside the frame, drawn where it is. */
export interface TripSpot {
  kind: "spot";
  x: number;
  y: number;
  keys: string[];
  label: string;
}

/** Trips whose places fall off the frame, drawn as one flag on its edge: a pill with an arrowhead pointing their way. */
export interface TripFlag {
  kind: "flag";
  x: number;
  y: number;
  width: number;
  height: number;
  /** The arrowhead's centre, at the flag's outer end, and the direction it points (radians, y down). */
  head: [number, number];
  angle: number;
  /** Where the label starts. */
  textAt: [number, number];
  keys: string[];
  label: string;
}

export type TripMark = TripSpot | TripFlag;

/** A rectangle in the frame. */
export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TripOptions {
  /** How far inside the frame's edge flags sit and spots must be. */
  inset: number;
  /** A flag's height. */
  height: number;
  /** A label's width as set. */
  measure: (label: string) => number;
  /** Places flags keep clear of: the scale, the credit. */
  reserved?: Box[];
}

/** "3.4 km", or "2.1–3.4 km" for several. */
export function kmText(kms: number[]): string {
  const low = Math.min(...kms);
  const high = Math.max(...kms);
  return low === high ? `${low} km` : `${low}–${high} km`;
}

/** A trip's label: its letters (when it has any) and its distance. */
export function tripLabel(keys: string[], kms: number[]): string {
  return keys.length ? `${keys.join(", ")} · ${kmText(kms)}` : kmText(kms);
}

/** Where the ray from `from` through `to` leaves the rectangle [low, high]; `from` is inside it. */
function exit(from: [number, number], to: [number, number], low: [number, number], high: [number, number]): [number, number] {
  const [dx, dy] = [to[0] - from[0], to[1] - from[1]];
  let t = Infinity;
  if (dx > 0) t = Math.min(t, (high[0] - from[0]) / dx);
  if (dx < 0) t = Math.min(t, (low[0] - from[0]) / dx);
  if (dy > 0) t = Math.min(t, (high[1] - from[1]) / dy);
  if (dy < 0) t = Math.min(t, (low[1] - from[1]) / dy);
  if (!Number.isFinite(t)) return from;
  return [from[0] + dx * t, from[1] + dy * t];
}

/** A point on the rectangle's edge as a distance along it, clockwise from the top-left corner. */
function along(point: [number, number], low: [number, number], high: [number, number]): number {
  const [x, y] = point;
  const [w, h] = [high[0] - low[0], high[1] - low[1]];
  const near = (a: number, b: number) => Math.abs(a - b) < 0.01;
  if (near(y, low[1])) return x - low[0];
  if (near(x, high[0])) return w + (y - low[1]);
  if (near(y, high[1])) return w + h + (high[0] - x);
  return 2 * w + h + (high[1] - y);
}

export function overlaps(a: Box, b: Box, gap = 0): boolean {
  return a.x < b.x + b.width + gap && b.x < a.x + a.width + gap && a.y < b.y + b.height + gap && b.y < a.y + a.height + gap;
}

interface Outside {
  trip: TripInput;
  at: number;
  angle: number;
}

/** One flag for a group of trips: on the edge where their mean direction from the site leaves the frame. */
function flagOf(group: Outside[], frame: Frame, options: TripOptions): TripFlag {
  const { inset, height, measure } = options;
  const low: [number, number] = [inset, inset];
  const high: [number, number] = [frame.width - inset, frame.height - inset];
  const site = frame.site;
  const [cx, cy] = group.reduce(([sx, sy], item) => [sx + Math.cos(item.angle), sy + Math.sin(item.angle)], [0, 0]);
  const angle = Math.atan2(cy, cx);
  const tip = exit(site, [site[0] + Math.cos(angle), site[1] + Math.sin(angle)], low, high);
  const ordered = [...group].sort((a, b) => (a.trip.key ?? "").localeCompare(b.trip.key ?? ""));
  const keys = ordered.map((item) => item.trip.key).filter((key): key is string => Boolean(key));
  const label = tripLabel(keys, ordered.map((item) => item.trip.km));
  const width = measure(label) + 24;
  const sides = [tip[0] - low[0], high[0] - tip[0], tip[1] - low[1], high[1] - tip[1]];
  const side = sides.indexOf(Math.min(...sides));
  const across = clamp(tip[1] - height / 2, low[1], high[1] - height);
  const lengthwise = clamp(tip[0] - width / 2, low[0], high[0] - width);
  let box: Box =
    side === 0
      ? { x: low[0], y: across, width, height }
      : side === 1
        ? { x: high[0] - width, y: across, width, height }
        : { x: lengthwise, y: side === 2 ? low[1] : high[1] - height, width, height };
  box = clear(box, side < 2 ? "y" : "x", options.reserved ?? [], low, high);
  // The arrowhead sits at the end the trips lie beyond: the outer end on the sides, the nearer end on top and bottom.
  const headRight = side === 1 || (side >= 2 && Math.cos(angle) > 0.2);
  const head: [number, number] = [headRight ? box.x + box.width - 9 : box.x + 9, box.y + height / 2];
  return {
    kind: "flag",
    x: tenth(box.x),
    y: tenth(box.y),
    width: tenth(width),
    height,
    head: [tenth(head[0]), tenth(head[1])],
    angle,
    textAt: [tenth(headRight ? box.x + 7 : box.x + 17), tenth(box.y + height / 2 + 3.4)],
    keys,
    label,
  };
}

/** The box moved as little as it takes off the reserved places, staying within [low, high]: along `axis` (along its
    edge) when it can, else across it, just past what blocks it. */
function clear(box: Box, axis: "x" | "y", reserved: Box[], low: [number, number], high: [number, number]): Box {
  const free = (moved: Box) =>
    moved.x >= low[0] - 0.01 &&
    moved.y >= low[1] - 0.01 &&
    moved.x + moved.width <= high[0] + 0.01 &&
    moved.y + moved.height <= high[1] + 0.01 &&
    !reserved.some((place) => overlaps(moved, place, 2));
  if (free(box)) return box;
  const candidates: { moved: Box; cost: number }[] = [];
  for (const place of reserved) {
    for (const x of [place.x - box.width - 3, place.x + place.width + 3]) {
      candidates.push({ moved: { ...box, x }, cost: Math.abs(x - box.x) * (axis === "x" ? 1 : 1.5) });
    }
    for (const y of [place.y - box.height - 3, place.y + place.height + 3]) {
      candidates.push({ moved: { ...box, y }, cost: Math.abs(y - box.y) * (axis === "y" ? 1 : 1.5) });
    }
  }
  return candidates.filter(({ moved }) => free(moved)).sort((a, b) => a.cost - b.cost)[0]?.moved ?? box;
}

/** The trips in the frame: a spot where a place is inside it, else a flag on the edge in its direction from the site;
    flags that would overlap become one, labelled with all their letters and their range. */
export function placeTrips(trips: TripInput[], frame: Frame, options: TripOptions): TripMark[] {
  const { inset } = options;
  const low: [number, number] = [inset, inset];
  const high: [number, number] = [frame.width - inset, frame.height - inset];
  const site = frame.site;
  const spots: TripSpot[] = [];
  const outside: Outside[] = [];
  for (const trip of trips) {
    const [x, y] = frame.at(trip.point);
    if (x >= low[0] && x <= high[0] && y >= low[1] && y <= high[1]) {
      spots.push({ kind: "spot", x, y, keys: trip.key ? [trip.key] : [], label: tripLabel(trip.key ? [trip.key] : [], [trip.km]) });
      continue;
    }
    const angle = Math.atan2(y - site[1], x - site[0]);
    outside.push({ trip, at: along(exit(site, [x, y], low, high), low, high), angle });
  }
  let groups = outside.sort((a, b) => a.at - b.at).map((item) => [item]);
  for (;;) {
    const flags = groups.map((group) => flagOf(group, frame, options));
    let pair: [number, number] | null = null;
    for (let i = 0; i < flags.length && !pair; i += 1) {
      for (let j = i + 1; j < flags.length && !pair; j += 1) {
        const [a, b] = [flags[i], flags[j]];
        if (a && b && overlaps(a, b, 3)) pair = [i, j];
      }
    }
    if (!pair) return [...spots, ...flags];
    const [i, j] = pair;
    groups = [...groups.filter((_, index) => index !== i && index !== j), [...(groups[i] ?? []), ...(groups[j] ?? [])]];
  }
}
/** A poster trip's place, from its distance and bearing from the site. */
export function tripPoint(site: LatLon, trip: PosterTrip): LatLon {
  const metres = trip.km * 1000;
  const bearing = (trip.bearing * Math.PI) / 180;
  const [lat0, lon0] = site;
  const kx = METRES_PER_DEGREE * Math.cos((lat0 * Math.PI) / 180);
  return [lat0 + (metres * Math.cos(bearing)) / METRES_PER_DEGREE, lon0 + (metres * Math.sin(bearing)) / kx];
}

// ---------- The site's tag and the scale ----------

/** Where the site's tag goes: of the four corners around the site's mark, the one over the fewest pins (a numbered
    pin counts ten dots), inside the frame. */
export function placeTag(frame: Frame, size: { width: number; height: number }, pins: PinMark[], radius: number): Box {
  const [x, y] = frame.site;
  const { width, height } = size;
  const corners: Box[] = [
    { x: x + 11, y: y - 25, width, height },
    { x: x - 11 - width, y: y - 25, width, height },
    { x: x + 11, y: y + 11, width, height },
    { x: x - 11 - width, y: y + 11, width, height },
  ];
  const cost = (box: Box) => {
    const outside = box.x < 4 || box.y < 4 || box.x + box.width > frame.width - 4 || box.y + box.height > frame.height - 4;
    const covered = pins.reduce((sum, pin) => {
      const r = pin.numbered ? radius : 3;
      return overlaps(box, { x: pin.x - r, y: pin.y - r, width: 2 * r, height: 2 * r }) ? sum + (pin.numbered ? 10 : 1) : sum;
    }, 0);
    return covered + (outside ? 1000 : 0);
  };
  return corners.reduce((best, box) => (cost(box) < cost(best) ? box : best));
}

const NICE_METRES = [50, 100, 200, 250, 500, 1000, 2000, 2500, 5000];

/** The longest round distance whose bar fits `room` frame units. */
export function scaleBar(frame: Frame, room: number): { metres: number; length: number; label: string } {
  const metres = [...NICE_METRES].reverse().find((m) => m * frame.scale <= room) ?? NICE_METRES[0] ?? 50;
  return { metres, length: tenth(metres * frame.scale), label: metres >= 1000 ? `${metres / 1000} km` : `${metres} m` };
}

// ---------- The kit's payload ----------

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStreetMap(value: unknown): value is StreetMap {
  return isObject(value) && Array.isArray(value.box) && isObject(value.streets) && Array.isArray(value.water);
}

/** The cover's map in a kit's dossier (`dossier.cover.map`); null in kits made before it existed. */
export function coverMapOf(cover: object | null | undefined): CoverMap | null {
  const map: unknown = cover && "map" in cover ? cover.map : null;
  if (!isObject(map) || !Array.isArray(map.pins) || !Array.isArray(map.trips) || typeof map.caption !== "string") return null;
  return { ...(map as unknown as CoverMap), streets: isStreetMap(map.streets) ? map.streets : null };
}

/** The poster's map in a kit (`poster.map`); null in kits made before it existed. */
export function posterMapOf(poster: object | null | undefined): PosterMap | null {
  const map: unknown = poster && "map" in poster ? poster.map : null;
  if (!isObject(map) || !Array.isArray(map.trips)) return null;
  return {
    streets: isStreetMap(map.streets) ? map.streets : null,
    trips: map.trips as PosterTrip[],
    caption: typeof map.caption === "string" ? map.caption : null,
  };
}
