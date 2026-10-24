import { describe, expect, it, vi } from "vitest";
import {
  createExamplesStore,
  exampleChips,
  exampleFound,
  exampleLead,
  exampleTags,
  exampleTesting,
  exampleWho,
  INITIAL_EXAMPLES,
  kitExample,
  readExamples,
  shortArea,
  surveyExample,
} from "./examples";
import { EXAMPLE_AGES, EXAMPLE_DRIVE, EXAMPLE_IDEA, EXAMPLES } from "./fixtures";

describe("examples", () => {
  it("asks the server once per page load, however many screens want them", async () => {
    const fetchExamples = vi.fn(() => Promise.resolve(EXAMPLES));
    const store = createExamplesStore(fetchExamples);
    expect(store.get()).toEqual(INITIAL_EXAMPLES);
    const heard = vi.fn();
    const stop = store.subscribe(heard);
    await Promise.all([store.load(), store.load()]);
    await store.load();
    expect(fetchExamples).toHaveBeenCalledTimes(1);
    expect(store.get()).toEqual({ phase: "ready", list: EXAMPLES });
    expect(heard).toHaveBeenCalledTimes(1);
    stop();
  });

  it("shows nothing when the request fails, and does not ask again", async () => {
    const fetchExamples = vi.fn(() => Promise.reject(new TypeError("Failed to fetch")));
    const store = createExamplesStore(fetchExamples);
    await store.load();
    await store.load();
    expect(store.get()).toEqual({ phase: "ready", list: [] });
    expect(fetchExamples).toHaveBeenCalledTimes(1);
  });

  it("keeps only examples it can open, and reads anything but a list as none", () => {
    expect(readExamples(null)).toEqual([]);
    expect(readExamples({ detail: "Not found" })).toEqual([]);
    expect(readExamples("[]")).toEqual([]);
    const broken = [{ run_id: "", url: "/s/x", label: "X" }, { url: "/s/y", label: "Y" }, null, 7, { ...EXAMPLE_AGES, label: " " }];
    expect(readExamples([EXAMPLE_DRIVE, ...broken, EXAMPLE_IDEA])).toEqual([EXAMPLE_DRIVE, EXAMPLE_IDEA]);
  });

  it("reads an example's missing lists, counts and kit as empty", () => {
    const [bare] = readExamples([{ run_id: "r9", url: "/s/r9", label: "Fort Greene, Brooklyn", kit: { token: "t" } }]);
    expect(bare).toEqual({
      run_id: "r9",
      url: "/s/r9",
      label: "Fort Greene, Brooklyn",
      intent: "explore",
      area: "",
      llm: false,
      concepts: [],
      gaps: 0,
      top_gaps: [],
      kit: null,
    });
    expect(bare && exampleTags(bare)).toEqual([]);
    expect(bare && exampleFound(bare)).toBe("0 categories ranked");
    expect(bare && exampleLead(bare)).toBeNull();
    const [noisy] = readExamples([{ ...EXAMPLE_AGES, concepts: ["", "Poppy Taproom", 3], top_gaps: "Lounge", gaps: "8" }]);
    expect(noisy).toMatchObject({ concepts: ["Poppy Taproom"], top_gaps: [], gaps: 0 });
  });

  it("finds the example of a survey's id, and of a kit's token", () => {
    expect(surveyExample(EXAMPLES, "d2aa4df573aa")).toBe(EXAMPLE_AGES);
    expect(surveyExample(EXAMPLES, "r1")).toBeNull();
    expect(surveyExample(EXAMPLES, null)).toBeNull();
    expect(surveyExample([], "d2aa4df573aa")).toBeNull();
    expect(kitExample(EXAMPLES, EXAMPLE_DRIVE.kit?.token)).toBe(EXAMPLE_DRIVE);
    expect(kitExample(EXAMPLES, "another-kit")).toBeNull();
    expect(kitExample(EXAMPLES, "")).toBeNull();
    expect(kitExample(EXAMPLES, undefined)).toBeNull();
  });

  it("says who a survey served and which idea it tested", () => {
    expect(exampleWho(EXAMPLE_AGES)).toBe("For 25–34");
    expect(exampleWho(EXAMPLE_DRIVE)).toBeNull();
    expect(exampleTesting(EXAMPLE_IDEA)).toBe("Testing: Starbucks");
    expect(exampleTesting(EXAMPLE_DRIVE)).toBeNull();
    expect(exampleTesting({ ...EXAMPLE_IDEA, business: null })).toBeNull();
    expect(exampleTags(EXAMPLE_DRIVE)).toEqual(["10 km drive"]);
    expect(exampleTags(EXAMPLE_AGES)).toEqual(["10-minute walk", "For 25–34"]);
    expect(exampleTags(EXAMPLE_IDEA)).toEqual(["10-minute walk", "Testing: Starbucks"]);
  });

  it("says the area as chips do on the first screen's small cards", () => {
    expect(shortArea("10-minute walk")).toBe("10-min walk");
    expect(shortArea("30-minute drive")).toBe("30-min drive");
    expect(shortArea("25 km drive")).toBe("25 km drive");
    expect(shortArea("12.5 km drive")).toBe("12.5 km drive");
    expect(shortArea("a 10-minute walk away")).toBe("a 10-minute walk away");
    expect(exampleChips(EXAMPLE_DRIVE)).toEqual(["10 km drive"]);
    expect(exampleChips(EXAMPLE_AGES)).toEqual(["10-min walk", "For 25–34"]);
    expect(exampleChips(EXAMPLE_IDEA)).toEqual(["10-min walk", "Testing: Starbucks"]);
  });

  it("says what a survey found, and what it leads with", () => {
    expect(exampleFound(EXAMPLE_DRIVE)).toBe("8 categories ranked · most missing: Personal care, Hamburger restaurant, Coffee shop");
    expect(exampleFound({ ...EXAMPLE_DRIVE, gaps: 1, top_gaps: ["Bakery"] })).toBe("1 category ranked · most missing: Bakery");
    expect(exampleFound({ ...EXAMPLE_DRIVE, top_gaps: [] })).toBe("8 categories ranked");
    expect(exampleLead(EXAMPLE_DRIVE)).toBe("Smash & Shroom");
    expect(exampleLead({ ...EXAMPLE_DRIVE, headline: null })).toBe("Smash & Shroom");
    expect(exampleLead({ ...EXAMPLE_DRIVE, headline: " ", concepts: [] })).toBe("Personal care");
    expect(exampleLead({ ...EXAMPLE_DRIVE, headline: null, concepts: [], top_gaps: [] })).toBeNull();
  });
});
