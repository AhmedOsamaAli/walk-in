import { describe, expect, it } from "vitest";
import {
  areaKey,
  areaLabel,
  areaNoun,
  areaOf,
  areaShort,
  asArea,
  isTravel,
  km2Text,
  parseKm,
  parseMinutes,
  walkLabel,
  walkShort,
  WALK_10,
} from "./area";

describe("the numbers typed in Other", () => {
  it("takes whole minutes from 5 to 60", () => {
    expect(parseMinutes("20")).toBe(20);
    expect(parseMinutes(" 5 ")).toBe(5);
    expect(parseMinutes("60")).toBe(60);
    expect(parseMinutes("4")).toBeNull();
    expect(parseMinutes("61")).toBeNull();
    expect(parseMinutes("7.5")).toBeNull();
    expect(parseMinutes("")).toBeNull();
    expect(parseMinutes("ten")).toBeNull();
  });

  it("takes 1 to 100 km with one decimal at most, written with a point or a comma", () => {
    expect(parseKm("25")).toBe(25);
    expect(parseKm("2.5")).toBe(2.5);
    expect(parseKm("2,5")).toBe(2.5);
    expect(parseKm("2.")).toBe(2);
    expect(parseKm("1")).toBe(1);
    expect(parseKm("100")).toBe(100);
    expect(parseKm("0.5")).toBeNull();
    expect(parseKm("100.5")).toBeNull();
    expect(parseKm("2.55")).toBeNull();
    expect(parseKm("-3")).toBeNull();
  });
});

describe("the area in words", () => {
  it("says it as the server does, in sentences and on chips", () => {
    expect(areaLabel({ travel: "walk", minutes: 10 })).toBe("10-minute walk");
    expect(areaLabel({ travel: "drive", minutes: 30 })).toBe("30-minute drive");
    expect(areaLabel({ travel: "distance", km: 25 })).toBe("25 km drive");
    expect(areaShort({ travel: "walk", minutes: 10 })).toBe("10-min walk");
    expect(areaShort({ travel: "drive", minutes: 30 })).toBe("30-min drive");
    expect(areaShort({ travel: "distance", km: 2.5 })).toBe("2.5 km drive");
    expect(areaNoun({ travel: "walk", minutes: 10 })).toBe("walk");
    expect(areaNoun({ travel: "distance", km: 25 })).toBe("drive");
  });

  it("prefers the traced area's own words, and makes them for an older survey", () => {
    const traced = { minutes: 30, source: "street network", ring: [], area_km2: 210.4, radius_m: 9000 };
    expect(walkShort({ ...traced, travel: "drive", label: "30-minute drive", short: "30-min drive" })).toBe("30-min drive");
    expect(walkShort({ ...traced, travel: "drive", label: "30-minute drive" })).toBe("30-minute drive");
    expect(walkShort({ ...traced, travel: "distance", km: 25, minutes: 41 })).toBe("25 km drive");
    expect(walkShort({ ...traced, minutes: 15 })).toBe("15-min walk");
    expect(walkLabel({ ...traced, travel: "drive", label: "30-minute drive", short: "30-min drive" })).toBe("30-minute drive");
    expect(walkLabel({ ...traced, minutes: 15 })).toBe("15-minute walk");
    expect(walkLabel({ ...traced, travel: "distance", km: 12.5 })).toBe("12.5 km drive");
  });

  it("gives big areas round numbers", () => {
    expect(km2Text(0.503)).toBe("0.503");
    expect(km2Text(1.21)).toBe("1.21");
    expect(km2Text(15.27)).toBe("15.3");
    expect(km2Text(210.4)).toBe("210");
    expect(km2Text(1924.4)).toBe("1,924");
  });
});

describe("areaOf", () => {
  it("reads a survey made before drives and distances as a walk", () => {
    expect(areaOf({ minutes: 15 })).toEqual({ travel: "walk", minutes: 15 });
    expect(areaOf({})).toEqual(WALK_10);
  });

  it("reads drives and distances, and falls back to the 10-minute walk for values out of the limits", () => {
    expect(areaOf({ travel: "drive", minutes: 30 })).toEqual({ travel: "drive", minutes: 30 });
    expect(areaOf({ travel: "distance", km: 25, minutes: 41 })).toEqual({ travel: "distance", km: 25 });
    expect(areaOf({ travel: "drive", minutes: 90 })).toEqual(WALK_10);
    expect(areaOf({ travel: "distance", km: null })).toEqual(WALK_10);
    expect(areaOf({ travel: "teleport", minutes: 20 })).toEqual({ travel: "walk", minutes: 20 });
    expect(isTravel("toString")).toBe(false);
  });

  it("keys an area by what it measures, and reads a bare number of minutes as a walk", () => {
    expect(areaKey({ travel: "drive", minutes: 30 })).toBe("drive:30");
    expect(areaKey({ travel: "distance", km: 2.5 })).toBe("distance:2.5");
    expect(asArea(15)).toEqual({ travel: "walk", minutes: 15 });
  });
});
