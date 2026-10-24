import { describe, expect, it } from "vitest";
import type { GapRow } from "../api/types";
import {
  agentText,
  coords,
  dataAsOfText,
  gapWhy,
  list,
  naturalList,
  queriesText,
  replayText,
  safeUrl,
  shortLabel,
  standingText,
  topicForms,
} from "./format";

describe("survey freshness", () => {
  const now = new Date(2026, 9, 22, 18, 0);

  it("counts every Qloo answer a survey read, wherever it was kept", () => {
    expect(queriesText({ run_id: "r", seconds: 9, qloo_calls: 0, cache_hits: 69, qloo_queries: 69 })).toBe("69 Qloo queries");
    // Surveys saved before every read was counted add the two counters.
    expect(queriesText({ run_id: "r", seconds: 9, qloo_calls: 50, cache_hits: 7 })).toBe("57 Qloo queries");
    expect(queriesText({ run_id: "r", seconds: 9, qloo_calls: 1, cache_hits: 0 })).toBe("1 Qloo query");
  });

  it("dates the data only when it is from an earlier day", () => {
    expect(dataAsOfText(new Date(2026, 9, 22, 9, 0).toISOString(), now)).toBeNull();
    expect(dataAsOfText(new Date(2026, 9, 20, 9, 0).toISOString(), now)).toMatch(/^Qloo data as of .*20/);
    expect(dataAsOfText(null, now)).toBeNull();
    expect(dataAsOfText("not a date", now)).toBeNull();
  });

  it("mentions concepts designed earlier only when that was another day, and never the quota", () => {
    expect(replayText({ saved_at: new Date(2026, 9, 22, 8, 0).getTime() / 1000, model: "m" }, now)).toBeNull();
    const earlier = replayText({ saved_at: new Date(2026, 9, 19, 8, 0).getTime() / 1000, model: "m" }, now);
    expect(earlier).toMatch(/^The agent designed these concepts on .* from this same Qloo evidence$/);
    expect(earlier).not.toMatch(/cache|quota|replay/i);
  });
});

const base: GapRow = {
  genre_id: "urn:tag:genre:place:seafood",
  genre: "Seafood",
  demand_rank: 1,
  ref_rank: 8,
  nearby_count: 1,
  nearby_capped: false,
  favorites_kind: "local",
  favorites_total: 6,
  favorites_far: 5,
  median_favorite_km: 3.2,
  expected_nearby: 4,
  lift: 0,
  relative_supply: 1,
  leakage: null,
  evidence: "ok",
  gap_score: 67,
};

describe("gapWhy", () => {
  it("states each signal in one sentence", () => {
    expect(gapWhy({ ...base, lift: 0.7, relative_supply: 0.5, leakage: 0.75 })).toBe(
      "Loved more here than in the areas around; fewer places than a block this dense usually has; people here travel for their own favorites.",
    );
  });

  it("flags thin and atypical evidence", () => {
    expect(gapWhy({ ...base, evidence: "thin" })).toBe("Qloo knows too few places of this type here to judge.");
    expect(gapWhy({ ...base, relative_supply: 1.6, evidence: "atypical" })).toBe(
      "Already well supplied; favorites are mostly hotels or malls.",
    );
  });

  it("falls back to a neutral sentence", () => {
    expect(gapWhy(base)).toBe("Demand and supply look typical for this block.");
  });
});

describe("formatting", () => {
  it("writes coordinates with hemispheres", () => {
    expect(coords(30.2622, -97.7247)).toBe("N 30.2622 · W 97.7247");
    expect(coords(-33.8688, 151.2093)).toBe("S 33.8688 · E 151.2093");
  });

  it("shortens geocoder labels to two parts", () => {
    expect(shortLabel("Fort Greene, Brooklyn, Kings County, New York, United States")).toBe("Fort Greene, Brooklyn");
    expect(shortLabel(null)).toBe("Selected site");
  });

  it("coerces agent lists", () => {
    expect(list(["Oysters", "", 3, null, { a: 1 }])).toEqual(["Oysters", "3"]);
    expect(list("Natural wine")).toEqual(["Natural wine"]);
    expect(list(undefined)).toEqual([]);
  });

  it("joins lists the way a sentence does", () => {
    expect(naturalList(["Williamsburg", "Greenpoint", "Bushwick"])).toBe("Williamsburg, Greenpoint and Bushwick");
    expect(naturalList(["Williamsburg", "Greenpoint"])).toBe("Williamsburg and Greenpoint");
    expect(naturalList(["Williamsburg"])).toBe("Williamsburg");
    expect(naturalList([])).toBe("");
  });

  it("only allows https images and inline raster images", () => {
    expect(safeUrl("https://images.qloo.com/i/a.jpg")).toBe("https://images.qloo.com/i/a.jpg");
    expect(safeUrl("data:image/jpeg;base64,AAAA")).toBe("data:image/jpeg;base64,AAAA");
    expect(safeUrl("http://example.com/a.jpg")).toBeNull();
    expect(safeUrl("data:image/svg+xml;base64,AAAA")).toBeNull();
    expect(safeUrl("javascript:alert(1)")).toBeNull();
  });

  it("badges established places by Michelin first, then review count", () => {
    expect(standingText({ reviews: 1563, michelin: "1 star" })).toBe("Michelin 1 star");
    expect(standingText({ reviews: null, michelin: "listed" })).toBe("Michelin listed");
    expect(standingText({ reviews: 1563 })).toBe("1,563 reviews");
    expect(standingText(null)).toBe("");
  });

  it("lists a topic's other wordings, not its label", () => {
    const waits = { label: "Long waits and lines", mentions: 189, places: 12, keywords: ["long lines", "wait time", "on line", "long wait times"] };
    expect(topicForms(waits)).toEqual(["long lines", "wait time", "on line"]);
    expect(topicForms({ label: "croissant", mentions: 9, places: 3, keywords: ["croissant", "croissants"] })).toEqual(["croissants"]);
  });

  it("describes the agent's tool calls", () => {
    expect(agentText({ tool: "inspect_gap", args: { genre: "Seafood", reason: "Locals travel 3 km" } })).toBe(
      "Agent inspects the Seafood gap — Locals travel 3 km",
    );
    expect(agentText({ tool: "fan_taste", args: { category: "Wine bar" } })).toBe(
      "Agent asks Qloo what fans of Wine bar around here also love",
    );
    expect(agentText({ tool: "something_new", args: null })).toBe("Agent calls something_new");
  });
});
