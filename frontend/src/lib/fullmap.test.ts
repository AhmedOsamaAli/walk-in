import { describe, expect, it } from "vitest";
import {
  DROPPED_PIN,
  expandLabel,
  FULL_MAP_ENTRY,
  isFullMapEntry,
  searchText,
  SITE_ZOOM,
  spotTitle,
  STREET_ZOOM,
  streetZoom,
  walkReach,
} from "./fullmap";

describe("streetZoom", () => {
  it("frames a new site at street level when its whole walk fits there", () => {
    expect(streetZoom(17)).toBe(SITE_ZOOM);
    expect(streetZoom(SITE_ZOOM)).toBe(SITE_ZOOM);
  });

  it("steps out to 15 when the walk is wider than the screen at 16, and never further", () => {
    expect(streetZoom(15)).toBe(STREET_ZOOM);
    expect(streetZoom(14)).toBe(STREET_ZOOM);
    expect(streetZoom(11)).toBe(STREET_ZOOM);
  });
});

describe("walkReach", () => {
  it("reaches as far as the circle drawn for an area that cannot be traced", () => {
    expect(walkReach(10)).toBe(800);
    expect(walkReach(5)).toBe(400);
    expect(walkReach({ travel: "walk", minutes: 15 })).toBe(1200);
    expect(walkReach({ travel: "drive", minutes: 10 })).toBe(4000);
    expect(walkReach({ travel: "distance", km: 10 })).toBe(7000);
  });
});

describe("spotTitle", () => {
  it("calls the site by its address", () => {
    expect(spotTitle("Zamalek, Cairo", 30.0626, 31.2197)).toEqual({ text: "Zamalek, Cairo", isCoords: false });
  });

  it("gives a pin placed by hand its coordinates", () => {
    expect(spotTitle(DROPPED_PIN, 30.0626, 31.2197)).toEqual({ text: "N 30.0626 · E 31.2197", isCoords: true });
    expect(spotTitle(null, 40.735, -73.975)).toEqual({ text: "N 40.7350 · W 73.9750", isCoords: true });
    expect(spotTitle("  ", 40.735, -73.975).isCoords).toBe(true);
  });
});

describe("searchText", () => {
  it("names the site set, so a search box never names another one", () => {
    expect(searchText("Zamalek, Cairo")).toBe("Zamalek, Cairo");
    expect(searchText(" 26th of July Street, Zamalek ")).toBe("26th of July Street, Zamalek");
  });

  it("says nothing for a pin placed by hand, or no site", () => {
    expect(searchText(DROPPED_PIN)).toBe("");
    expect(searchText(null)).toBe("");
    expect(searchText(undefined)).toBe("");
    expect(searchText("  ")).toBe("");
  });
});

describe("the corner control", () => {
  it("names what it does either way", () => {
    expect(expandLabel(false)).toBe("Full-screen map");
    expect(expandLabel(true)).toBe("Exit full screen");
  });

  it("recognizes the history entry the full-screen map adds", () => {
    expect(isFullMapEntry(FULL_MAP_ENTRY)).toBe(true);
    expect(isFullMapEntry({ ...FULL_MAP_ENTRY })).toBe(true);
    expect(isFullMapEntry(null)).toBe(false);
    expect(isFullMapEntry({ walkinFullMap: "yes" })).toBe(false);
  });
});
