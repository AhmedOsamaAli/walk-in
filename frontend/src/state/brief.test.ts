import { describe, expect, it } from "vitest";
import { runParams } from "../api/client";
import { floorArea } from "../lib/format";
import { initialBrief, missing, runRequest, unitLine, type BriefForm } from "./brief";

const site = { id: "east_austin", label: "East Austin, Texas", lat: 30.2622, lon: -97.7247 };
const place = { id: "4F04-6D7D", name: "Suerte", genres: ["Mexican"], lat: 30.26228, lon: -97.72328 };
const form = (patch: Partial<BriefForm>): BriefForm => ({ ...initialBrief, ...patch });

describe("brief", () => {
  it("says what still stops the survey", () => {
    expect(missing(null, initialBrief)).toBe("Choose a site first.");
    expect(missing(site, initialBrief)).toBeNull();
    expect(missing(site, form({ intent: "open", business: "  " }))).toBe("Say what you want to open.");
    expect(missing(site, form({ intent: "improve" }))).toBe("Find your place on Qloo first.");
    expect(missing(site, form({ intent: "improve", place }))).toBeNull();
    expect(missing(site, form({ area: "5" }))).toMatch(/between 10 and 2,000 m²/);
    expect(missing(site, form({ intent: "improve", place, area: "5" }))).toBeNull(); // the unit is not asked there
  });

  it("converts the floor area to square meters", () => {
    expect(floorArea("60", "m2")).toBe(60);
    expect(floorArea("650", "ft2")).toBe(60.4);
    expect(floorArea("60,5", "m2")).toBe(60.5);
    expect(floorArea("", "m2")).toBeNull();
    expect(floorArea("abc", "m2")).toBeNull();
    expect(floorArea("30000", "ft2")).toBeNull();
  });

  it("asks the server for an explore survey with the unit the owner described", () => {
    const run = runRequest(site, form({ focus: "food_drink", notes: " no alcohol ", area: "60", kitchen: "light", outdoor: "no" }));
    expect(run).toMatchObject({ intent: "explore", focus: "food_drink", notes: "no alcohol", sizeM2: 60, kitchen: "light", outdoor: false });
    expect(unitLine(run)).toBe("60 m² · Light prep, no hood · No outdoor space");
    const params = new URLSearchParams(runParams(run));
    expect(Object.fromEntries(params)).toMatchObject({ intent: "explore", size_m2: "60", kitchen: "light", outdoor: "false" });
    expect(params.has("business") || params.has("place_id")).toBe(false);
  });

  it("sends the business to open, over any business type", () => {
    const run = runRequest(site, form({ intent: "open", business: "  bakery ", focus: "retail" }));
    expect(run).toMatchObject({ intent: "open", business: "bakery", focus: "any" });
    expect(unitLine(run)).toBeNull();
    expect(new URLSearchParams(runParams(run)).get("business")).toBe("bakery");
  });

  it("compares the owner's place without unit details or notes", () => {
    const run = runRequest(site, form({ intent: "improve", place, notes: "halal", area: "60", kitchen: "full" }));
    expect(run).toMatchObject({ intent: "improve", placeId: "4F04-6D7D", notes: "", focus: "any" });
    const params = new URLSearchParams(runParams(run));
    expect(params.get("place_id")).toBe("4F04-6D7D");
    expect(params.has("size_m2") || params.has("kitchen") || params.has("outdoor")).toBe(false);
  });
});
