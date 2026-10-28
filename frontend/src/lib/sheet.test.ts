import { describe, expect, it } from "vitest";
import type { Concept, Design, LaunchPlan } from "../api/types";
import { AUDIENCE_CLEAR, AUDIENCE_GENERAL } from "./audience.fixtures";
import { offerItems, sheetTabs, unitText } from "./sheet";

const CONCEPT: Concept = {
  name: "Copper Kitchen",
  genre: "Seafood",
  gap_score: 99,
  signature: ["House seafood special", "Croissant"],
  beat_competitors:
    "1 seafood place inside the walk; it is Seafood Nearby 0 (4.0★), known for croissant and outdoor seating. Stand apart " +
    "with what the seafood places people here love are known for and none inside the walk is: house seafood special and fish and chips.",
};

function plan(lines: string[]): LaunchPlan {
  return {
    audience: { crowd: [], artists: [], podcasts: [], screen: [], brands: [], shared: [] },
    where: { minutes: 10, reach_m: null, neighborhoods: [], sites_like: [] },
    when: { times: [], intents: [] },
    claims: lines.map((line) => ({ kind: "new", line, proof: "2 of the seafood places locals love are known for it; none inside the walk is." })),
    channels: [],
    cautions: [],
  };
}

describe("the sheet's offer", () => {
  it("marks what the evidence says: new to the block, else known at the places people here love", () => {
    const design: Design = { mode: "rules", offer: ["House seafood special", "Croissant", "Clam  chowder", "Fish and chips", "croissant"] };
    expect(offerItems(design, CONCEPT)).toEqual([
      { item: "House seafood special", mark: "new" },
      // The concept's own pick: its competition line does not name it, so nothing is claimed for it.
      { item: "Croissant", mark: null },
      { item: "Clam chowder", mark: "loved" },
      { item: "Fish and chips", mark: "new" },
    ]);
  });

  it("takes a 'new' claim of the launch plan as evidence too, and only a whole item of the competition line", () => {
    const design: Design = { mode: "rules", offer: ["Croissant", "Chips", "Oysters"], launch: plan(["Croissant, which no seafood place within a 10-minute walk is known for"]) };
    expect(offerItems(design, CONCEPT).map((item) => item.mark)).toEqual(["new", "loved", "loved"]);
    // "a, b and c": every part before the last comma is an item, and the last part is two.
    const three = { ...CONCEPT, beat_competitors: "Stand apart with what they are known for and none inside the walk that Qloo lists is: oysters, clam chowder and lobster roll." };
    expect(offerItems({ mode: "rules", offer: ["Oysters", "Lobster roll", "Clam chowder", "Lobster"] }, three).map((item) => item.mark)).toEqual([
      "new",
      "new",
      "new",
      "loved",
    ]);
    // A single item may hold an "and" of its own.
    const one = { ...CONCEPT, beat_competitors: "Stand apart with what they are known for and none inside the walk is: fish and chips." };
    expect(offerItems({ mode: "rules", offer: ["Fish and chips", "Chips"] }, one).map((item) => item.mark)).toEqual(["new", "loved"]);
    // Drives and distances name their area, and an age focus names whose favorites count.
    const drive = {
      ...CONCEPT,
      beat_competitors:
        "Stand apart with what the seafood places people here aged 25–34 love are known for and none inside the 10 km drive " +
        "that Qloo lists is: lobster roll.",
    };
    expect(offerItems({ mode: "rules", offer: ["Lobster roll", "Oysters"] }, drive).map((item) => item.mark)).toEqual(["new", "loved"]);
  });

  it("claims nothing for a sheet a model wrote, beyond what the evidence names", () => {
    const design: Design = { mode: "agent", offer: ["Smoked trout toast", "House seafood special", "Fish and chips"] };
    expect(offerItems(design, CONCEPT)).toEqual([
      { item: "Smoked trout toast", mark: null },
      { item: "House seafood special", mark: "new" },
      { item: "Fish and chips", mark: "new" },
    ]);
    // Without every item of the line's last part on the sheet, that part cannot be read for sure: nothing is claimed.
    expect(offerItems({ mode: "agent", offer: ["House seafood special", "Chips"] }, CONCEPT).map((item) => item.mark)).toEqual([null, null]);
    expect(offerItems({ offer: "Oysters" }, { name: "x", genre: "Seafood", gap_score: null })).toEqual([{ item: "Oysters", mark: "loved" }]);
    expect(offerItems({ offer: null }, CONCEPT)).toEqual([]);
  });
});

describe("the unit in words", () => {
  it("says only what the owner gave", () => {
    expect(unitText({ size: "60 m² (646 ft²)", kitchen: "a light-prep kitchen", outdoor_space: "none" })).toBe(
      "60 m² (646 ft²), a light-prep kitchen, no outdoor space",
    );
    expect(unitText({ size: "unknown", kitchen: "unknown", outdoor_space: "yes" })).toBe("outdoor space");
    expect(unitText({ size: "unknown", kitchen: "unknown", outdoor_space: "unknown" })).toBeNull();
    expect(unitText(null)).toBeNull();
  });
});

describe("the sheet's tabs", () => {
  const shown = (tabs: ReturnType<typeof sheetTabs>) => tabs.map(({ label, teaser }) => [label, teaser]);
  const CONCEPT_TAB = ["Concept", "What it sells and how it runs, drawn from the evidence and your rules."];
  const KIT_TAB = ["Launch kit", "Ad copy, a window poster, tracked links and a report for a landlord or a lender."];

  it("name the people to win, and say where and when to reach them when there is a launch plan", () => {
    expect(shown(sheetTabs(AUDIENCE_CLEAR, true))).toEqual([
      CONCEPT_TAB,
      ["Who you'd win", "Who the places people here love draw, by age, and where and when to reach them."],
      KIT_TAB,
    ]);
    expect(shown(sheetTabs(AUDIENCE_GENERAL, false))[1]).toEqual([
      "Who it draws",
      "Who this kind of place draws, by age, compared with everyone.",
    ]);
  });

  it("keep a launch plan's tab without an audience, and leave out the people when there is neither", () => {
    expect(shown(sheetTabs(null, true))[1]).toEqual([
      "Who to reach",
      "Who to reach, where and when, and only what the evidence lets an ad say.",
    ]);
    expect(sheetTabs(undefined, false).map((tab) => tab.id)).toEqual(["concept", "kit"]);
  });
});
