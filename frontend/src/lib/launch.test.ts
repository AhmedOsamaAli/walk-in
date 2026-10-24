import { describe, expect, it } from "vitest";
import type { LaunchPlan } from "../api/types";
import { areaText, audienceRows, hasLaunchPlan, reachText, shareText } from "./launch";

const plan: LaunchPlan = {
  audience: { crowd: [], artists: [], podcasts: [], screen: [], brands: [], shared: [] },
  where: { minutes: 10, reach_m: 883, neighborhoods: [], sites_like: [] },
  when: { times: [], intents: [], hours: null },
  claims: [],
  channels: [],
  cautions: ["Name no competitor in an ad."],
};

describe("shareText", () => {
  it("counts the places a tag rests on", () => {
    expect(shareText({ label: "Families", places: 3, of: 4 })).toBe("3 of 4 places");
    expect(shareText({ label: "Families", places: 1, of: 1 })).toBe("1 of 1 place");
  });
});

describe("audienceRows", () => {
  it("keeps the kinds that have names, in a fixed order", () => {
    const audience = { ...plan.audience, brands: ["Patagonia"], artists: ["Gary Clark Jr.", "Mobley"] };
    expect(audienceRows(audience)).toEqual([
      { title: "Artists", names: ["Gary Clark Jr.", "Mobley"] },
      { title: "Brands", names: ["Patagonia"] },
    ]);
  });
});

describe("hasLaunchPlan", () => {
  it("leaves out a plan with nothing to act on", () => {
    expect(hasLaunchPlan(null)).toBe(false);
    expect(hasLaunchPlan(plan)).toBe(false);
  });

  it("keeps a plan with a claim, a channel or an audience", () => {
    expect(hasLaunchPlan({ ...plan, claims: [{ kind: "new", line: "Kouign amann", proof: "2 of 3" }] })).toBe(true);
    expect(hasLaunchPlan({ ...plan, channels: [{ channel: "Nextdoor", setting: "Holly", why: "" }] })).toBe(true);
    expect(hasLaunchPlan({ ...plan, audience: { ...plan.audience, podcasts: ["Stassi"] } })).toBe(true);
  });
});

describe("the plan's area", () => {
  it("says the server's name for the area, and a walk for plans made before drives", () => {
    expect(areaText({ ...plan.where, label: "30-minute drive" })).toBe("30-minute drive");
    expect(areaText({ ...plan.where, label: "25 km drive" })).toBe("25 km drive");
    expect(areaText(plan.where)).toBe("10-minute walk");
  });

  it("says how far it reaches in metres, then kilometres", () => {
    expect(reachText(883)).toBe("883 m");
    expect(reachText(999)).toBe("999 m");
    expect(reachText(14_240)).toBe("14.2 km");
  });
});
