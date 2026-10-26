import { describe, expect, it } from "vitest";
import { initialSurvey } from "../state/survey";
import { AUDIENCE_CLEAR, AUDIENCE_GENERAL } from "./audience.fixtures";
import { KIT_PARTS } from "./kitParts";
import { sheetTabs } from "./sheet";
import { surveyTabs } from "./surveyTabs";
import type { TabItem } from "./tabs";

/** Every tab set the app draws: the survey's for each kind of survey, the design sheet's in each form, the kit's. */
const SETS: Record<string, TabItem[]> = {
  "a survey to find what's missing": surveyTabs({ ...initialSurvey, intent: "explore" }),
  "a survey to test an idea": surveyTabs({ ...initialSurvey, intent: "open" }),
  "a survey to improve a place": surveyTabs({ ...initialSurvey, intent: "improve" }),
  "a design sheet": sheetTabs(AUDIENCE_CLEAR, true),
  "a design sheet with a category's audience": sheetTabs(AUDIENCE_GENERAL, false),
  "a design sheet with a launch plan only": sheetTabs(null, true),
  "a launch kit": KIT_PARTS.map((part) => ({ ...part })),
};

const HYPE = /\b(unlock|magic|powerful|supercharge|amazing|incredible|ultimate|seamless|revolutionary|game-changing)/i;

describe("the tabs' teasers", () => {
  it.each(Object.entries(SETS))("give every tab of %s one line of its own", (_, tabs) => {
    const teasers = tabs.map((tab) => tab.teaser ?? "");
    expect(teasers.every(Boolean)).toBe(true);
    expect(new Set(teasers).size).toBe(tabs.length);
  });

  it("are one short sentence each, in plain words", () => {
    for (const teaser of Object.values(SETS).flatMap((tabs) => tabs.map((tab) => tab.teaser ?? ""))) {
      expect(teaser).toMatch(/^[A-Z][^.]*\.$/);
      expect(teaser.length).toBeLessThanOrEqual(100);
      expect(teaser).not.toMatch(HYPE);
    }
  });
});
