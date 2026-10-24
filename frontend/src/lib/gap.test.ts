import { describe, expect, it } from "vitest";
import type { GapRow, OsmCheck } from "../api/types";
import {
  leadLine,
  osmConfirmed,
  osmDetail,
  osmExtra,
  osmLink,
  osmUnchecked,
  readingLabel,
  readingTone,
  supplyCount,
  TRAVEL_READING,
} from "./gap";

function gap(over: Partial<GapRow> = {}): GapRow {
  return {
    genre_id: "urn:tag:genre:place:restaurant:bakery",
    genre: "Bakery",
    demand_rank: 6,
    ref_rank: 14,
    nearby_count: 2,
    nearby_capped: false,
    favorites_kind: "local",
    favorites_total: 5,
    favorites_far: 4,
    median_favorite_km: 2.1,
    expected_nearby: 5.2,
    lift: 0.8,
    relative_supply: 0.6,
    leakage: 0.71,
    evidence: "ok",
    gap_score: 64,
    ...over,
  };
}

const JOES = { name: "Joe's Bakery & Coffee Shop", lat: 30.26, lon: -97.72, url: "https://www.openstreetmap.org/node/1", tag: "shop=bakery", distance_m: 610 };
const INSOMNIA = { name: "Insomnia Cookies", lat: 30.263, lon: -97.727, url: "https://www.openstreetmap.org/way/2", tag: "shop=pastry", distance_m: 331 };

function checked(over: Partial<OsmCheck> = {}): OsmCheck {
  return { checked: true, count: 4, extra: [INSOMNIA, JOES], credit: "© OpenStreetMap contributors", ...over };
}

describe("the badge", () => {
  it("reads 'People here travel for it', in older surveys too", () => {
    expect(TRAVEL_READING).toBe("People here travel for it");
    expect(readingLabel("Locals travel for it")).toBe("People here travel for it");
    expect(readingLabel("People here travel for it")).toBe("People here travel for it");
    expect(readingLabel("Clear gap")).toBe("Clear gap");
    expect(readingLabel(undefined)).toBeNull();
  });

  it("highlights real gaps and mutes uncertain ones", () => {
    for (const label of ["Clear gap", "Under-supplied", "People here travel for it", "Locals travel for it"]) {
      expect(readingTone(label)).toBe("strong");
    }
    for (const label of ["Crowded", "Thin data", "Atypical"]) expect(readingTone(label)).toBe("weak");
    expect(readingTone("Steady demand")).toBe("");
  });

  it("leads with the line that explains it", () => {
    const why = [
      "People here rank bakery #6 among the place types they engage with.",
      "Only 4 bakeries inside the 10-minute walk (2 on Qloo, 2 more on OpenStreetMap), where a block this dense usually has about 5.2.",
      "4 of the 5 bakeries people here love more than the rest of the city does are outside the walk (median 2.1 km).",
    ];
    expect(leadLine(gap({ reading: "Locals travel for it", why }))).toBe(why[2]);
    expect(leadLine(gap({ reading: "People here travel for it", why }))).toBe(why[2]);
    expect(leadLine(gap({ reading: "Clear gap", why }))).toBe(why[1]);
    expect(leadLine(gap({ reading: "Top demand", why }))).toBe(why[0]);
  });
});

describe("the OpenStreetMap cross-check", () => {
  it("counts the places only OpenStreetMap shows as supply", () => {
    expect(supplyCount(gap({ osm: checked() }))).toBe(4);
    expect(supplyCount(gap())).toBe(2);
  });

  it("keeps only located places that link to OpenStreetMap", () => {
    const bad = [
      { ...JOES, url: "javascript:alert(1)" },
      { ...JOES, url: "https://example.com/node/1" },
      { ...JOES, lat: Number.NaN },
      { ...JOES, name: " " },
    ];
    expect(osmExtra(gap({ osm: checked({ extra: [INSOMNIA, ...bad] }) }))).toEqual([INSOMNIA]);
    expect(osmLink("https://www.openstreetmap.org/node/1")).toBe("https://www.openstreetmap.org/node/1");
    expect(osmLink("http://openstreetmap.org.evil.test/node/1")).toBeNull();
  });

  it("says why a gap was not cross-checked, and nothing for surveys saved before the check existed", () => {
    expect(osmUnchecked({ checked: false, count: 0, extra: [], reason: "unmapped" })).toBe(
      "Not cross-checked: no OpenStreetMap tag reliably marks this kind of place.",
    );
    expect(osmUnchecked({ checked: false, count: 0, extra: [], reason: "unavailable" })).toBe(
      "Not cross-checked: OpenStreetMap did not answer in time.",
    );
    expect(osmUnchecked({ checked: false, count: 0, extra: [], reason: "off" })).toBe("Not cross-checked with OpenStreetMap.");
    expect(osmUnchecked(undefined)).toBeNull();
    expect(osmUnchecked(checked())).toBeNull();
  });

  it("confirms Qloo's count when OpenStreetMap shows nothing more", () => {
    expect(osmConfirmed(checked({ extra: [], count: 0 }))).toBe("OpenStreetMap shows none inside the walk either.");
    expect(osmConfirmed(checked({ extra: [], count: 3 }))).toBe("OpenStreetMap shows 3 inside the walk, all on Qloo's list too.");
    expect(osmConfirmed(checked({ extra: [], note: "Qloo lists more places of this kind…" }))).toBe("Qloo lists more places of this kind…");
    expect(osmConfirmed(checked())).toBeNull();
    expect(osmDetail(INSOMNIA)).toBe("331 m away · shop=pastry");
  });
});
