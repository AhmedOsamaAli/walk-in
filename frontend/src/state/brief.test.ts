import { describe, expect, it } from "vitest";
import { areaParams, runParams } from "../api/client";
import type { RunSite } from "../api/types";
import { floorArea } from "../lib/format";
import {
  AGES_LABELS,
  agesLine,
  areaProblem,
  briefArea,
  briefOf,
  catchmentLines,
  foodPrepAsked,
  formArea,
  initialBrief,
  missing,
  runRequest,
  unitLine,
  type BriefForm,
} from "./brief";
import { DISTANCE_SITE, DRIVE_SITE, DRIVE_WALK } from "./fixtures";

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

  it("rebuilds a recorded survey's brief, which asks the server for the same survey again", () => {
    const run = runRequest(
      site,
      form({ intent: "open", business: "bakery", minutes: 15, notes: "halal", area: "650", areaUnit: "ft2", kitchen: "light", outdoor: "yes" }),
    );
    const recorded: RunSite = {
      lat: run.lat,
      lon: run.lon,
      label: run.label,
      focus: run.focus,
      notes: run.notes,
      minutes: run.minutes,
      size_m2: run.sizeM2 ?? null,
      kitchen: run.kitchen ?? null,
      outdoor: run.outdoor ?? null,
      intent: run.intent,
      business: run.business ?? "",
      place_id: "",
    };
    const brief = briefOf(recorded, null);
    expect(brief.site).toEqual({ id: null, label: site.label, lat: site.lat, lon: site.lon });
    expect(brief.form).toMatchObject({ intent: "open", business: "bakery", minutes: 15, area: "60.4", areaUnit: "m2" });
    expect(runParams(runRequest(brief.site, brief.form))).toBe(runParams(run));
  });

  it("rebuilds a drive for an age group, which asks the server for the same survey again", () => {
    const run = runRequest(site, form({ intent: "open", business: "gym", travel: "drive", otherMinutes: "45", ages: "35_54" }));
    const recorded: RunSite = {
      lat: run.lat,
      lon: run.lon,
      label: run.label,
      focus: run.focus,
      notes: run.notes,
      minutes: run.minutes,
      intent: run.intent,
      business: run.business ?? "",
      travel: run.travel ?? "walk",
      km: run.km ?? null,
      ages: run.ages ?? "all",
    };
    const brief = briefOf(recorded, null);
    expect(brief.form).toMatchObject({ travel: "drive", minutes: 10, otherMinutes: "45", ages: "35_54" });
    expect(runParams(runRequest(brief.site, brief.form))).toBe(runParams(run));
  });

  it("finds the owner's place again in a recorded improve survey", () => {
    const recorded: RunSite = { ...site, label: "Suerte", minutes: 10, intent: "improve", place_id: place.id };
    const brief = briefOf(recorded, { name: "Suerte", genres: ["Mexican"], lat: place.lat, lon: place.lon });
    expect(brief.form.place).toEqual({ id: place.id, name: "Suerte", genres: ["Mexican"], lat: place.lat, lon: place.lon });
    expect(missing(brief.site, brief.form)).toBeNull();
    expect(runRequest(brief.site, brief.form)).toMatchObject({ intent: "improve", placeId: place.id });
  });

  it("falls back to the brief's defaults for values it does not know", () => {
    const odd: RunSite = {
      lat: 1,
      lon: 2,
      label: "Pin",
      intent: "teleport",
      focus: "space",
      minutes: 70,
      kitchen: "huge",
      size_m2: Number.NaN,
      travel: "rocket",
      ages: "toddlers",
    };
    expect(briefOf(odd, null).form).toEqual(initialBrief);
  });
});

describe("how far customers come from", () => {
  it("asks for a 10-minute walk until the owner picks another area", () => {
    expect(briefArea(initialBrief)).toEqual({ travel: "walk", minutes: 10 });
    const params = new URLSearchParams(runParams(runRequest(site, initialBrief)));
    expect(Object.fromEntries(params)).toMatchObject({ travel: "walk", minutes: "10" });
    expect(params.has("km") || params.has("ages")).toBe(false);
  });

  it("sends a drive's minutes, and a road distance's km without minutes", () => {
    const drive = new URLSearchParams(runParams(runRequest(site, form({ travel: "drive", minutes: 30 }))));
    expect(Object.fromEntries(drive)).toMatchObject({ travel: "drive", minutes: "30" });
    const road = new URLSearchParams(runParams(runRequest(site, form({ travel: "distance", km: 25 }))));
    expect(Object.fromEntries(road)).toMatchObject({ travel: "distance", km: "25" });
    expect(road.has("minutes")).toBe(false);
    expect(areaParams({ travel: "distance", km: 2.5 })).toEqual({ travel: "distance", km: 2.5 });
    expect(areaParams({ travel: "walk", minutes: 15 })).toEqual({ travel: "walk", minutes: 15 });
  });

  it("takes the number typed in Other over the quick pick, and the pick again once Other is emptied", () => {
    expect(briefArea(form({ travel: "drive", minutes: 30, otherMinutes: "45" }))).toEqual({ travel: "drive", minutes: 45 });
    expect(briefArea(form({ travel: "distance", km: 25, otherKm: "2,5" }))).toEqual({ travel: "distance", km: 2.5 });
    expect(briefArea(form({ travel: "drive", minutes: 30, otherMinutes: " " }))).toEqual({ travel: "drive", minutes: 30 });
    // Walk and drive share their minutes; a distance keeps its own.
    expect(briefArea(form({ travel: "walk", otherMinutes: "20", otherKm: "500" }))).toEqual({ travel: "walk", minutes: 20 });
    expect(runRequest(site, form({ travel: "drive", otherMinutes: "45" }))).toMatchObject({ travel: "drive", minutes: 45 });
  });

  it("stops the survey while Other holds a number out of the limits, and traces nothing meanwhile", () => {
    const short = form({ travel: "walk", otherMinutes: "3" });
    expect(briefArea(short)).toBeNull();
    expect(areaProblem(short)).toBe("A walk must be between 5 and 60 minutes.");
    expect(missing(site, short)).toBe("A walk must be between 5 and 60 minutes.");
    expect(missing(site, form({ travel: "drive", otherMinutes: "90" }))).toBe("A drive must be between 5 and 60 minutes.");
    expect(missing(site, form({ travel: "distance", otherKm: "0.5" }))).toBe("The distance must be between 1 and 100 km.");
    expect(missing(site, form({ travel: "distance", otherMinutes: "3" }))).toBeNull(); // the walk's Other is not in use
    // The quick pick still stands in for the lede.
    expect(formArea(short)).toEqual({ travel: "walk", minutes: 10 });
  });

  it("rebuilds a drive, a road distance and a number off the quick picks from a recorded survey", () => {
    const drive = briefOf(DRIVE_SITE, null);
    expect(drive.site.label).toBe("Round Rock, Texas");
    expect(drive.form).toMatchObject({ travel: "drive", minutes: 30, otherMinutes: "", ages: "25_34" });
    const custom = briefOf({ ...site, travel: "walk", minutes: 20 }, null).form;
    expect(custom).toMatchObject({ travel: "walk", minutes: 10, otherMinutes: "20" });
    expect(briefArea(custom)).toEqual({ travel: "walk", minutes: 20 });
    const road = briefOf(DISTANCE_SITE, null).form;
    expect(road).toMatchObject({ travel: "distance", km: 10, otherKm: "12.5" });
    expect(runParams(runRequest(site, road))).toContain("km=12.5");
    // Made before drives and distances: a walk, for everyone.
    expect(briefOf({ ...site, minutes: 15 }, null).form).toMatchObject({ travel: "walk", minutes: 15, ages: "all" });
  });
});

describe("food prep", () => {
  it("is asked only when food can be involved", () => {
    expect(foodPrepAsked(form({ intent: "explore", focus: "any" }))).toBe(true);
    expect(foodPrepAsked(form({ intent: "explore", focus: "food_drink" }))).toBe(true);
    expect(foodPrepAsked(form({ intent: "explore", focus: "retail" }))).toBe(false);
    expect(foodPrepAsked(form({ intent: "explore", focus: "leisure" }))).toBe(false);
    expect(foodPrepAsked(form({ intent: "open", focus: "retail" }))).toBe(true);
    expect(foodPrepAsked(form({ intent: "improve", focus: "any" }))).toBe(false);
  });

  it("stays out of the run while hidden, and comes back with the focus that asks for it", () => {
    const shop = form({ intent: "explore", focus: "retail", kitchen: "light", area: "60" });
    expect(runRequest(site, shop).kitchen).toBeUndefined();
    expect(new URLSearchParams(runParams(runRequest(site, shop))).has("kitchen")).toBe(false);
    expect(unitLine(runRequest(site, shop))).toBe("60 m²");
    const food = { ...shop, focus: "food_drink" as const };
    expect(runRequest(site, food).kitchen).toBe("light");
    expect(runRequest(site, form({ intent: "open", business: "bookstore", kitchen: "none" })).kitchen).toBe("none");
  });
});

describe("who the owner wants to serve", () => {
  it("names the area and the focus in the run header, in the server's words once traced", () => {
    const run = runRequest(site, form({ travel: "drive", minutes: 30, ages: "25_34" }));
    expect(catchmentLines(run, null)).toEqual(["30-min drive", "For 25–34"]);
    expect(catchmentLines(run, DRIVE_WALK)).toEqual(["30-min drive", "210 km²", "For 25–34"]);
    const walk = { minutes: 10, source: "street network", ring: [], area_km2: 1.21, radius_m: 640 };
    expect(catchmentLines(runRequest(site, initialBrief), walk)).toEqual(["10-min walk", "1.21 km²"]);
    expect(catchmentLines(runRequest(site, form({ travel: "distance", otherKm: "12.5" })), null)).toEqual(["12.5 km drive"]);
  });
  it("serves everyone until an age group is picked, which the run then asks for", () => {
    expect(initialBrief.ages).toBe("all");
    expect(runRequest(site, initialBrief).ages).toBeUndefined();
    const young = runRequest(site, form({ ages: "25_34" }));
    expect(young.ages).toBe("25_34");
    expect(new URLSearchParams(runParams(young)).get("ages")).toBe("25_34");
  });

  it("names the focus for the run header, and comes back with a recorded survey", () => {
    expect(agesLine("25_34")).toBe("For 25–34");
    expect(agesLine("55_plus")).toBe("For 55+");
    expect(agesLine("all")).toBeNull();
    expect(agesLine(undefined)).toBeNull();
    expect(Object.values(AGES_LABELS)).toEqual(["Everyone", "Under 25", "25–34", "35–54", "55+"]);
    expect(briefOf({ ...site, minutes: 10, ages: "under_25" }, null).form.ages).toBe("under_25");
  });
});
