import { describe, expect, it } from "vitest";
import type { LaunchPlan } from "../api/types";
import { areaText, audienceReach, audienceRows, hasLaunchPlan, reachText, shareText } from "./launch";

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

  it("says how far around the audiences were read, as the plan's basis line does", () => {
    const basis = (km: string) =>
      `Audiences are what people within ${km} over-index on compared with same-size areas around; the crowd, times and reasons to visit are Qloo's tags on the places people here love of this kind.`;
    expect(audienceReach(basis("1.5 km"))).toBe("1.5 km");
    expect(audienceReach(basis("7 km"))).toBe("7 km");
    expect(audienceReach(basis("6.469 km"))).toBe("6.5 km");
    expect(audienceReach(basis("12 km"))).toBe("12 km");
    expect(audienceReach(basis("14.6 km"))).toBe("15 km");
    expect(audienceReach(undefined)).toBe("1.5 km");
    expect(audienceReach("Audiences are what people here over-index on.")).toBe("1.5 km");
  });
});
