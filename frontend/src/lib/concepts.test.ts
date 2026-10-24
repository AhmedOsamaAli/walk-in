import { describe, expect, it } from "vitest";
import type { Concept } from "../api/types";
import {
  changeNotes,
  combinesText,
  conceptsNote,
  loves,
  placeConcepts,
  riskText,
  ruleLines,
  ruleNames,
} from "./concepts";

const CAUTION =
  "Untested: nothing like this exists nearby, so there is no direct proof people would come; it rests on two separate loves.";

function ranked(name: string, genre: string, score: number): Concept {
  return { name, genre, gap_score: score, risk: `Few ${genre.toLowerCase()} places nearby to learn from.` };
}

const WILD: Concept = {
  name: "Crumb & Chapter",
  genre: "Bakery",
  gap_score: null,
  wildcard: true,
  combines: [
    { item: "bakeries", genre: "Bakery", source: "People here rank bakeries #3 among place types, higher than the areas around (#9) (Qloo)." },
    { item: "bookstores", genre: "Bookstore", source: "People here travel a median 2.1 km to the bookstores they love most (Qloo)." },
  ],
  caution: CAUTION,
  risk: CAUTION,
};

describe("placeConcepts", () => {
  it("keeps the ranked concepts in order with their ranks, and the wild card last without one", () => {
    const concepts = [ranked("Tidewater", "Seafood", 67), ranked("Kahwa Corner", "Coffee shop", 51), WILD];
    expect(placeConcepts(concepts).map(({ concept, index, rank }) => [concept.name, index, rank])).toEqual([
      ["Tidewater", 0, 0],
      ["Kahwa Corner", 1, 1],
      ["Crumb & Chapter", 2, null],
    ]);
  });

  it("moves a wild card listed early to the end, keeping its index for its design sheet", () => {
    const concepts = [WILD, ranked("Tidewater", "Seafood", 67)];
    expect(placeConcepts(concepts).map(({ index, rank }) => [index, rank])).toEqual([
      [1, 0],
      [0, null],
    ]);
  });
});

describe("the wild card", () => {
  it("says what it combines, each love with its evidence", () => {
    expect(combinesText(WILD)).toBe("bakeries × bookstores");
    expect(loves(WILD).map((love) => love.source)).toEqual([
      "People here rank bakeries #3 among place types, higher than the areas around (#9) (Qloo).",
      "People here travel a median 2.1 km to the bookstores they love most (Qloo).",
    ]);
  });

  it("reads nothing from loves the payload left out or garbled", () => {
    expect(combinesText({ ...WILD, combines: null })).toBe("");
    expect(combinesText({ ...WILD, combines: [WILD.combines?.[0] ?? null] as Concept["combines"] })).toBe("");
    expect(loves({ ...WILD, combines: [{ item: "", genre: "Bakery", source: "x" }] })).toEqual([]);
  });

  it("states its caution once, not again as its risk", () => {
    expect(riskText(WILD)).toBeNull();
    expect(riskText({ ...WILD, risk: "Rent is high on this street." })).toBe("Rent is high on this street.");
    expect(riskText(ranked("Tidewater", "Seafood", 67))).toBe("Few seafood places nearby to learn from.");
  });
});

describe("the owner's rules", () => {
  it("lists how a concept keeps each rule, one line each", () => {
    const budget = "Budget prices: nothing in it is called upscale or premium.";
    expect(ruleLines({ ...WILD, owner_rules: [budget, " ", "No alcohol on the menu."] })).toEqual([
      budget,
      "No alcohol on the menu.",
    ]);
    expect(ruleLines(WILD)).toEqual([]);
  });

  it("names the rules read from the notes, capitalized and once each", () => {
    expect(ruleNames(["no alcohol", "budget prices", "no alcohol", " "])).toEqual(["No alcohol", "Budget prices"]);
  });

  it("lists what was dropped or changed once each", () => {
    const notes = [
      "Dropped Sahara Lounge (Hookah Bar): your notes rule it out (it serves alcohol).",
      "Kahwa Corner: took out Espresso martini (it serves alcohol).",
    ];
    expect(changeNotes({ notes: [...notes, notes[0]] })).toEqual(notes);
    expect(changeNotes({})).toEqual([]);
  });
});

describe("conceptsNote", () => {
  it("credits the agent, and says what the wild card is when there is one", () => {
    expect(conceptsNote({ mode: "agent", model: "gpt-oss-120b", concepts: [ranked("Tidewater", "Seafood", 67)] })).toBe(
      "Designed by the agent (gpt-oss-120b) from the gaps the survey found. Every claim traces back to Qloo evidence.",
    );
    expect(conceptsNote({ mode: "rules", concepts: [ranked("Tidewater", "Seafood", 67), WILD] })).toMatch(
      /deterministic rules.*The last is a wild card: two things people here love, combined\. It is untested, so it is not ranked\.$/,
    );
  });

  it("says why there are no concepts", () => {
    expect(conceptsNote({ mode: "none", note: "Not enough Qloo data around this site." })).toBe(
      "Not enough Qloo data around this site.",
    );
  });
});
