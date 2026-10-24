import { describe, expect, it } from "vitest";
import type { FavoritePlace, GapRow, PlaceCard } from "../api/types";
import {
  areaWord,
  awayText,
  countOf,
  declutter,
  gapPins,
  inSentence,
  insideLine,
  lovedInsideLine,
  median,
  medianFarKm,
  outsideLine,
  pinLabel,
  plural,
  roleText,
  samePlace,
  type Box,
} from "./pins";

const place = (id: string, name: string, lat: number | null, lon: number | null, distance?: number): PlaceCard => ({
  id,
  name,
  lat,
  lon,
  ...(distance === undefined ? {} : { distance_m: distance }),
});
const loved = (id: string, name: string, distance: number, within = false): FavoritePlace => ({
  ...place(id, name, 40.7 + distance / 111_320, -73.95, distance),
  within_walk: within,
});
/** A row as the server sends it now, with the median trip to the favorites outside the area. */
const withTrip = (gap: GapRow, km: number): GapRow => Object.assign(gap, { median_far_km: km });

function row(extra: Partial<GapRow> = {}): GapRow {
  return {
    genre_id: "urn:tag:genre:place:restaurant:seafood",
    genre: "Seafood",
    demand_rank: 1,
    ref_rank: 8,
    nearby_count: 4,
    nearby_capped: false,
    favorites_kind: "local",
    favorites_total: 5,
    favorites_far: 5,
    median_favorite_km: 3.3,
    lift: 1,
    relative_supply: 0.2,
    leakage: 0.8,
    evidence: "ok",
    gap_score: 99,
    competitors: [
      place("c1", "Fish Shack", 40.7146, -73.9573, 120),
      place("c2", "Oyster Room", 40.716, -73.955, 380),
      place("c3", "No Location Grill", null, null),
      place("c4", "Crab Corner", 40.712, -73.961, 410),
    ],
    favorites: [
      loved("f1", "Harbor Oyster Bar", 2500),
      loved("f2", "Dockside Crab", 2900),
      loved("f3", "Saltwater Kitchen", 3300),
      loved("f4", "Pier Nine Fish", 3700),
      loved("f5", "Tidal Grill", 4100),
    ],
    ...extra,
  };
}

describe("gapPins", () => {
  it("numbers the competitors in list order and letters the loved places, skipping places with no location", () => {
    const pins = gapPins(row());
    expect(pins.pins.map((pin) => `${pin.mark} ${pin.name}`)).toEqual([
      "1 Fish Shack",
      "2 Oyster Room",
      "3 Crab Corner",
      "A Harbor Oyster Bar",
      "B Dockside Crab",
      "C Saltwater Kitchen",
      "D Pier Nine Fish",
      "E Tidal Grill",
    ]);
    expect(pins.competitors.map((mark) => mark?.mark ?? null)).toEqual(["1", "2", null, "3"]);
    expect(pins.favorites.map((mark) => mark?.mark)).toEqual(["A", "B", "C", "D", "E"]);
    expect(new Set(pins.pins.map((pin) => pin.key)).size).toBe(pins.pins.length);
  });

  it("lists only what the row lists: six of each", () => {
    const many = Array.from({ length: 9 }, (_, k) => place(`c${k}`, `Place ${k}`, 40.71, -73.95, 100 + k));
    const pins = gapPins(row({ competitors: many, favorites: [] }));
    expect(pins.pins.map((pin) => pin.mark)).toEqual(["1", "2", "3", "4", "5", "6"]);
  });

  it("gives a loved place that is also a competitor the competitor's number, and one pin", () => {
    const twin: FavoritePlace = { ...place("c2", "Oyster Room", 40.716, -73.955, 380), within_walk: true };
    const pins = gapPins(row({ favorites: [twin, loved("f1", "Harbor Oyster Bar", 2500)] }));
    expect(pins.favorites.map((mark) => mark?.mark)).toEqual(["2", "A"]);
    expect(pins.pins.filter((pin) => pin.name === "Oyster Room")).toHaveLength(1);
    expect(pins.pins.find((pin) => pin.name === "Oyster Room")?.alsoLoved).toBe(true);
    expect(pins.summary.lovedInside).toBe(0);
  });

  it("numbers the places only OpenStreetMap shows after Qloo's", () => {
    const pins = gapPins(
      row({
        osm: {
          checked: true,
          count: 5,
          extra: [
            { name: "Lobster Hut", lat: 40.7139, lon: -73.9592, url: "https://www.openstreetmap.org/node/1", distance_m: 140 },
            { name: "", lat: 40.7139, lon: -73.9592, url: "https://www.openstreetmap.org/node/2" },
          ],
        },
      }),
    );
    const osm = pins.pins.filter((pin) => pin.role === "osm");
    expect(osm.map((pin) => `${pin.mark} ${pin.name}`)).toEqual(["4 Lobster Hut"]);
    expect(pins.osm.map((mark) => mark?.mark)).toEqual(["4"]);
    expect(pins.summary.osm).toBe(1);
  });

  it("leaves out loved places far beyond where they are searched, but never a place inside the area", () => {
    const pins = gapPins(row({ favorites: [loved("x", "Across the ocean", 5_000_000), loved("f1", "Near", 900)] }));
    expect(pins.favorites.map((mark) => mark?.mark ?? null)).toEqual([null, "A"]);
    // A drive or a road distance reaches far: its competitors, and loved places inside it, are drawn however far.
    const far = gapPins(
      row({
        competitors: [place("c9", "Roadside Fish", 41.4, -73.95, 80_000)],
        favorites: [loved("f9", "Lakeside Grill", 75_000, true)],
      }),
    );
    expect(far.pins.map((pin) => `${pin.mark} ${pin.name}`)).toEqual(["1 Roadside Fish", "A Lakeside Grill"]);
  });

  it("names the area as the survey measured it", () => {
    const { summary, pins } = gapPins(row());
    expect(areaWord(undefined)).toBe("the walk");
    expect(areaWord("walk")).toBe("the walk");
    expect(areaWord("drive")).toBe("the drive");
    expect(areaWord("distance")).toBe("the drive");
    expect(insideLine(summary, "the drive")).toBe("Inside the drive: 3 of 4 seafood places");
    expect(outsideLine(summary, "the drive")).toBe("Loved, outside the drive: 5 of 5");
    const [first] = pins;
    if (!first) throw new Error("missing pin");
    expect(roleText(first, "the drive")).toBe("Inside the drive");
    expect(pinLabel(first)).toBe("1, Fish Shack: inside the walk");
  });

  it("sums up what the legend shows", () => {
    const { summary } = gapPins(row());
    expect(summary).toMatchObject({
      inside: 3,
      insideTotal: 4,
      osm: 0,
      outside: 5,
      favoritesFar: 5,
      favoritesTotal: 5,
      medianFarKm: null,
      lovedInside: 0,
    });
    expect(insideLine(summary)).toBe("Inside the walk: 3 of 4 seafood places");
    expect(insideLine({ ...summary, inside: 4 })).toBe("Inside the walk: 4 seafood places");
    expect(insideLine({ ...summary, inside: 1, insideTotal: 1 })).toBe("Inside the walk: 1 seafood place");
    expect(insideLine({ ...summary, inside: 6, insideTotal: 50, insideCapped: true })).toBe(
      "Inside the walk: 6 of 50+ seafood places",
    );
    expect(outsideLine(summary)).toBe("Loved, outside the walk: 5 of 5");
    expect(outsideLine({ ...summary, medianFarKm: 3.3 })).toBe("Loved, outside the walk: 5 of 5 · median 3.3 km");
    expect(outsideLine({ ...summary, kind: "citywide", favoritesFar: 8, favoritesTotal: 10, medianFarKm: 12 }, "the drive")).toBe(
      "City's famous spots, outside the drive: 8 of 10 · median 12.0 km",
    );
    expect(lovedInsideLine({ ...summary, lovedInside: 2 })).toBe("Loved, inside the walk: 2");
  });

  it("says the favorites in the server's numbers, as the gap row does, not in the six pins it draws", () => {
    // Seven loved places, all outside: the map letters six (A–F), whose own median trip would be 4.1 km.
    const seven = [1900, 2600, 3400, 3900, 4300, 4600, 5200].map((m, k) => loved(`f${k}`, `Loved ${k}`, m));
    const gap = withTrip(row({ favorites: seven, favorites_total: 7, favorites_far: 7, median_favorite_km: 3.9 }), 3.9);
    const { summary, pins } = gapPins(gap);
    expect(pins.filter((pin) => pin.role === "loved").map((pin) => pin.mark)).toEqual(["A", "B", "C", "D", "E", "F"]);
    expect(summary).toMatchObject({ outside: 6, favoritesFar: 7, favoritesTotal: 7, medianFarKm: 3.9 });
    expect(outsideLine(summary)).toBe("Loved, outside the walk: 7 of 7 · median 3.9 km");
    // Some loved places inside the area: the median is the trip to the ones outside, the server's median_far_km.
    const some = gapPins(withTrip(row({ favorites_total: 7, favorites_far: 4, median_favorite_km: 1.2 }), 3.4));
    expect(outsideLine(some.summary, "the drive")).toBe("Loved, outside the drive: 4 of 7 · median 3.4 km");
  });

  it("gives no distance for a row saved before the server measured the trip outside", () => {
    const old = gapPins(row({ median_favorite_km: 2.8 }));
    expect(old.summary.medianFarKm).toBeNull();
    expect(outsideLine(old.summary)).toBe("Loved, outside the walk: 5 of 5");
    expect(medianFarKm(Object.assign(row(), { median_far_km: "3.4" }))).toBeNull();
    expect(medianFarKm(Object.assign(row(), { median_far_km: null }))).toBeNull();
    expect(medianFarKm(withTrip(row(), 0.8))).toBe(0.8);
  });

  it("marks the city's famous spots as famous, and loved places inside the walk as inside", () => {
    const famous = gapPins(row({ favorites_kind: "citywide" }));
    expect(new Set(famous.pins.filter((pin) => pin.mark >= "A").map((pin) => pin.role))).toEqual(new Set(["famous"]));
    const inside = gapPins(row({ favorites: [loved("w1", "Corner Cellar", 150, true)] }));
    expect(inside.summary).toMatchObject({ outside: 0, lovedInside: 1 });
  });
});

describe("the words", () => {
  it("reads a category inside a sentence", () => {
    expect(inSentence("Wine Bar")).toBe("wine bar");
    expect(inSentence("Mexican")).toBe("Mexican");
    expect(inSentence("New American")).toBe("New American");
    expect(plural("Coffee shop")).toBe("coffee shops");
    expect(plural("Bakery")).toBe("bakeries");
    expect(plural("Seafood")).toBe("seafood places");
    expect(plural("Bar + Grill")).toBe("bar + grill places");
    expect(countOf("Bakery", 1)).toBe("1 bakery");
    expect(countOf("Bakery", 50, true)).toBe("50+ bakeries");
  });

  it("names a pin by its role and distance", () => {
    const { pins } = gapPins(row());
    const [first] = pins;
    const lettered = pins.find((pin) => pin.mark === "C");
    if (!first || !lettered) throw new Error("missing pins");
    expect(roleText(first)).toBe("Inside the walk");
    expect(roleText(lettered)).toBe("Loved by people here · 3.3 km away");
    expect(pinLabel(lettered)).toBe("C, Saltwater Kitchen: loved by people here, 3.3 km away");
    expect(awayText(640)).toBe("640 m away");
    expect(awayText(null)).toBe("");
  });

  it("takes medians and tells places apart", () => {
    expect(median([])).toBeNull();
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(samePlace(place("a", "Fish", 1, 1), place("a", "Other name", 1, 1))).toBe(true);
    expect(samePlace(place("a", "Fish", 1, 1), place("b", "Fish", 1, 1))).toBe(false);
    expect(samePlace({ name: "Fish ", lat: 40.7, lon: -73.95 }, { name: "fish", lat: 40.7001, lon: -73.95 })).toBe(true);
    expect(samePlace({ name: "Fish", lat: 40.7, lon: -73.95 }, { name: "Fish", lat: 40.71, lon: -73.95 })).toBe(false);
  });
});

describe("declutter", () => {
  const site = { x: 100, y: 100 };
  const keepClear: Box[] = [{ left: 87, top: 87, right: 113, bottom: 113 }];
  const hit = (a: { x: number; y: number }, b: { x: number; y: number }, size: number) =>
    Math.abs(a.x - b.x) < size && Math.abs(a.y - b.y) < size;

  it("leaves badges with room where they are", () => {
    expect(declutter([{ x: 10, y: 10 }, { x: 200, y: 40 }], 24, keepClear, site)).toEqual([
      { x: 0, y: 0 },
      { x: 0, y: 0 },
    ]);
  });

  it("moves crowded badges apart and off the site, away from it first", () => {
    const points = [
      { x: 100, y: 100 },
      { x: 104, y: 98 },
      { x: 120, y: 100 },
      { x: 121, y: 102 },
    ];
    const offsets = declutter(points, 24, keepClear, site);
    const placed = points.map((point, k) => ({ x: point.x + (offsets[k]?.x ?? 0), y: point.y + (offsets[k]?.y ?? 0) }));
    for (let i = 0; i < placed.length; i += 1) {
      const a = placed[i];
      if (!a) continue;
      expect(hit(a, site, 12 + 13)).toBe(false);
      for (let j = i + 1; j < placed.length; j += 1) {
        const b = placed[j];
        if (b) expect(hit(a, b, 24)).toBe(false);
      }
    }
    // The badge east of the site moves on east.
    expect(offsets[2]?.x).toBeGreaterThan(0);
  });

  it("keeps a badge whose place is in view wholly in view, and leaves places out of view alone", () => {
    const view: Box = { left: 0, top: 0, right: 300, bottom: 150 };
    // Two places at the top edge: the first badge drops into view, the second finds room beside it, inside too.
    const offsets = declutter([{ x: 150, y: 4 }, { x: 156, y: 6 }, { x: 150, y: -40 }], 24, [], { x: 150, y: 100 }, view);
    const [first, second, outside] = offsets;
    expect(4 + (first?.y ?? 0) - 12).toBeGreaterThanOrEqual(0);
    expect(6 + (second?.y ?? 0) - 12).toBeGreaterThanOrEqual(0);
    expect(outside).toEqual({ x: 0, y: 0 });
  });
});
