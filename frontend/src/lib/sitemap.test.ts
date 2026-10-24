import { describe, expect, it } from "vitest";
import type { MapPin } from "../api/sitemap";
import type { LatLon } from "../api/types";
import {
  coverMapOf,
  dataEdge,
  fitFrame,
  kmText,
  linePath,
  localMetres,
  overlaps,
  placePins,
  placeTrips,
  posterMapOf,
  ringPath,
  scaleBar,
  tableNumbers,
  tripLabel,
  tripPoint,
  type TripFlag,
  type TripInput,
} from "./sitemap";

const SITE: LatLon = [40.7145, -73.958];
const M = 111_320;
const KX = M * Math.cos((SITE[0] * Math.PI) / 180);
/** A point `east` and `north` metres from the site. */
const off = (east: number, north: number): LatLon => [SITE[0] + north / M, SITE[1] + east / KX];
/** A diamond walk reaching 800 m from the site. */
const RING: LatLon[] = [off(-800, 0), off(0, 800), off(800, 0), off(0, -800), off(-800, 0)];
const measure = (label: string) => label.length * 6;

describe("the frame", () => {
  it("projects metres east and north of the site, as the server cuts its box", () => {
    const toLocal = localMetres(SITE);
    const [x, y] = toLocal(off(250, -400));
    expect(x).toBeCloseTo(250, 6);
    expect(y).toBeCloseTo(-400, 6);
  });

  it("fits the walk inside its padding, north up, at its true proportions", () => {
    const frame = fitFrame(RING, SITE, { width: 640, height: 400, pad: 40 });
    const points = RING.map(frame.at);
    expect(Math.min(...points.map(([, y]) => y))).toBeCloseTo(40, 0);
    expect(Math.max(...points.map(([, y]) => y))).toBeCloseTo(360, 0);
    expect(frame.site).toEqual([320, 200]);
    const [north, east] = [frame.at(off(0, 800)), frame.at(off(800, 0))];
    expect(north[1]).toBeLessThan(frame.site[1]); // north is up
    expect(east[0] - frame.site[0]).toBeCloseTo(frame.site[1] - north[1], 0); // a metre east is a metre north
    expect(frame.scale).toBeCloseTo(320 / 1600, 6);
  });

  it("slides toward the street data as far as the walk stays in view, and marks where the data stops", () => {
    // Data only east of 1,200 m west of the site: a wide frame centred on the walk would show 800 m beyond it.
    const box: [LatLon, LatLon] = [off(-1200, -1200), off(4000, 1200)];
    const centred = fitFrame(RING, SITE, { width: 800, height: 400, pad: 40 });
    const settled = fitFrame(RING, SITE, { width: 800, height: 400, pad: 40, box });
    expect(settled.site[0]).toBeLessThan(centred.site[0]);
    expect(settled.at(box[0])[0]).toBeCloseTo(0, 0);
    expect(RING.map(settled.at).every(([x]) => x >= 40 - 0.1)).toBe(true);
    expect(dataEdge(settled, box)).toBeNull();
    // Too little data to fill the frame: the walk stays in view and the frame says where the data stops.
    const small: [LatLon, LatLon] = [off(-900, -900), off(900, 900)];
    const framed = fitFrame(RING, SITE, { width: 800, height: 400, pad: 40, box: small });
    const edge = dataEdge(framed, small);
    expect(edge).not.toBeNull();
    expect(edge?.x).toBeGreaterThan(0);
    expect((edge?.x ?? 0) + (edge?.width ?? 0)).toBeLessThan(800);
  });

  it("writes lines and rings as one path each", () => {
    const frame = fitFrame(RING, SITE, { width: 640, height: 400, pad: 40 });
    expect(linePath([[SITE, off(0, 800)], [SITE]], frame.at)).toBe("M320 200L320 40");
    expect(ringPath([RING], frame.at)).toMatch(/^M\d.*Z$/);
    expect(ringPath([[SITE, SITE]], frame.at)).toBe("");
  });
});

describe("the pins", () => {
  const pin = (n: number | null, east: number, north: number, main = true): MapPin => {
    const [lat, lon] = off(east, north);
    return { n, name: `Place ${String(n ?? "dot")}`, lat, lon, main, distance_m: Math.round(Math.hypot(east, north)) };
  };

  it("keeps the survey's numbers, eases numbered pins off each other and the site, and leaves dots where they are", () => {
    const frame = fitFrame(RING, SITE, { width: 640, height: 400, pad: 40 });
    const pins = [pin(1, 300, 300), pin(2, 300, 300), pin(3, 305, 298, false), pin(4, 0, 0), pin(null, 300, 300)];
    const marks = placePins(pins, frame, 8);
    expect(marks.map((mark) => [mark.n, mark.numbered, mark.main])).toEqual([
      [1, true, true], [2, true, true], [3, true, false], [4, true, true], [null, false, true],
    ]);
    const numbered = marks.filter((mark) => mark.numbered);
    for (const a of numbered) {
      for (const b of numbered) if (a !== b) expect(Math.hypot(a.x - b.x, a.y - b.y)).toBeGreaterThanOrEqual(16);
      expect(Math.hypot(a.x - frame.site[0], a.y - frame.site[1])).toBeGreaterThanOrEqual(18);
    }
    const dot = marks.find((mark) => mark.n === null);
    expect(dot && [dot.x, dot.y]).toEqual(dot?.home);
    // The same pins land in the same places every time.
    expect(placePins(pins, frame, 8)).toEqual(marks);
  });

  it("gives each row of the competition table the number of its pin, and none to a row without a place on the map", () => {
    const pins = [pin(1, 100, 0), pin(2, 200, 0), pin(null, 300, 0)];
    const rows = [
      { name: "Place 1", distance_m: 100 },
      { name: "Nowhere", distance_m: null },
      { name: "Place 2", distance_m: 200 },
      { name: "Place dot", distance_m: 300 },
    ];
    expect(tableNumbers(rows, pins)).toEqual([1, null, 2, null]);
    expect(tableNumbers([{ name: "Someone else", distance_m: 100 }], pins)).toEqual([null]);
  });
});

describe("the trips", () => {
  const frame = fitFrame(RING, SITE, { width: 640, height: 400, pad: 40 });
  const trip = (key: string | null, km: number, bearing: number): TripInput => ({ key, km, point: tripPoint(SITE, { km, bearing }) });
  const options = { inset: 8, height: 16, measure };
  const flags = (marks: ReturnType<typeof placeTrips>) => marks.filter((mark): mark is TripFlag => mark.kind === "flag");

  it("puts a place inside the frame where it is, and one beyond it as a flag on the edge pointing its way", () => {
    const marks = placeTrips([trip("A", 0.9, 90), trip("B", 3.4, 0)], frame, options);
    const spot = marks.find((mark) => mark.kind === "spot");
    expect(spot && [spot.x, spot.y, spot.label]).toEqual([...frame.at(tripPoint(SITE, { km: 0.9, bearing: 90 })), "A · 0.9 km"]);
    const [flag] = flags(marks);
    expect(flag?.y).toBe(8); // due north: on the top edge
    expect(flag && flag.x < frame.site[0] && flag.x + flag.width > frame.site[0]).toBe(true);
    expect(flag?.angle).toBeCloseTo(-Math.PI / 2, 2); // pointing up the page
    expect(flag?.label).toBe("B · 3.4 km");
  });

  it("draws trips whose flags would overlap as one, with all their letters and their range", () => {
    const marks = placeTrips([trip("C", 2.1, 271), trip("A", 3.9, 269.5), trip("B", 2.6, 95)], frame, options);
    const drawn = flags(marks);
    expect(drawn.map((flag) => flag.label).sort()).toEqual(["A, C · 2.1–3.9 km", "B · 2.6 km"]);
    const west = drawn.find((flag) => flag.keys.join() === "A,C");
    expect(west?.x).toBe(8);
    const east = drawn.find((flag) => flag.keys.join() === "B");
    expect(east && east.x + east.width).toBeCloseTo(640 - 8, 1);
    for (const flag of drawn) {
      expect(flag.x).toBeGreaterThanOrEqual(8);
      expect(flag.x + flag.width).toBeLessThanOrEqual(640 - 8 + 0.1);
    }
    for (const a of drawn) for (const b of drawn) if (a !== b) expect(overlaps(a, b)).toBe(false);
  });

  it("keeps flags off the places it is told to keep clear", () => {
    const scale = { x: 640 - 128, y: 400 - 50, width: 128, height: 50 };
    const [flag] = flags(placeTrips([trip("D", 4.2, 120)], frame, { ...options, reserved: [scale] }));
    expect(flag && overlaps(flag, scale)).toBe(false);
    // A caption across nearly the whole top edge leaves no room along it: the flag sits just below the caption.
    const caption = { x: 8, y: 10, width: 600, height: 22 };
    const [north] = flags(placeTrips([trip("E", 3, 0)], frame, { ...options, reserved: [caption] }));
    expect(north && overlaps(north, caption)).toBe(false);
    expect(north?.y).toBe(35);
  });

  it("labels the poster's trips with their distance only", () => {
    const [flag] = flags(placeTrips([trip(null, 3.3, 200), trip(null, 3.1, 205)], frame, options));
    expect(flag?.label).toBe("3.1–3.3 km");
    expect(flag?.keys).toEqual([]);
  });

  it("writes distances and labels plainly", () => {
    expect(kmText([3.4])).toBe("3.4 km");
    expect(kmText([3.4, 2.1, 2.8])).toBe("2.1–3.4 km");
    expect(tripLabel(["A", "C"], [2.1, 3.9])).toBe("A, C · 2.1–3.9 km");
    expect(tripLabel([], [3.3])).toBe("3.3 km");
  });

  it("places a poster trip from its distance and bearing", () => {
    const [lat, lon] = tripPoint(SITE, { km: 1, bearing: 0 });
    expect(lat).toBeCloseTo(SITE[0] + 1000 / M, 8);
    expect(lon).toBeCloseTo(SITE[1], 8);
    const [, east] = localMetres(SITE)(tripPoint(SITE, { km: 2, bearing: 90 }));
    expect(east).toBeCloseTo(0, 6);
  });
});

describe("the scale and the payload", () => {
  it("draws the longest round distance that fits", () => {
    const frame = fitFrame(RING, SITE, { width: 640, height: 400, pad: 40 });
    expect(scaleBar(frame, 110)).toEqual({ metres: 500, length: 100, label: "500 m" });
    expect(scaleBar(frame, 250).label).toBe("1 km");
  });

  it("reads the maps a kit carries, and none from a kit made before them", () => {
    const streets = { box: [SITE, SITE], layers: ["primary"], streets: { primary: [] }, water: [], parks: [] };
    const cover = { concept: "Low Tide", map: { streets, pins: [], trips: [], caption: "No seafood place inside the 10-minute walk", basis: "" } };
    expect(coverMapOf(cover)?.caption).toBe("No seafood place inside the 10-minute walk");
    expect(coverMapOf({ ...cover, map: { ...cover.map, streets: null } })?.streets).toBeNull();
    expect(coverMapOf({ concept: "Old kit" })).toBeNull();
    expect(posterMapOf({ map: { streets, trips: [{ km: 3.4, bearing: 270 }], caption: null } })?.trips).toHaveLength(1);
    expect(posterMapOf({ name: "Old kit" })).toBeNull();
  });
});
