import { describe, expect, it } from "vitest";
import type { ConceptsPayload, GapRow, Verdict } from "../api/types";
import { initialSurvey, type SurveyState } from "../state/survey";
import { answerTab, hashTab, nextAction, openingTab, surveyTabs, tabNo } from "./surveyTabs";

const CONCEPTS: ConceptsPayload = {
  concepts: [
    { name: "Tidewater", genre: "Seafood", gap_score: 60 },
    { name: "Kahwa Corner", genre: "Coffee shop", gap_score: 51 },
    { name: "Crumb & Chapter", genre: "Bakery", gap_score: null, wildcard: true },
  ],
};
const GAPS = [{ genre: "Seafood" }, { genre: "Bakery" }] as GapRow[];
const VERDICT: Verdict = { query: "Coffee shop", found: true, level: "strong", headline: "A strong fit.", evidence: [] };

function survey(patch: Partial<SurveyState>): SurveyState {
  return { ...initialSurvey, ...patch };
}

describe("surveyTabs", () => {
  it("puts the answer first, then the evidence, the log last, for each kind of survey", () => {
    expect(surveyTabs(survey({ intent: "explore" })).map((tab) => tab.label)).toEqual([
      "Concepts",
      "Gaps",
      "The area",
      "Taste",
      "Log",
    ]);
    expect(surveyTabs(survey({ intent: "open" })).map((tab) => tab.id)).toEqual([
      "verdict",
      "concepts",
      "gaps",
      "area",
      "taste",
      "log",
    ]);
    expect(surveyTabs(survey({ intent: "improve" })).map((tab) => tab.label)[0]).toBe("What to change");
  });

  it("dims every tab but the log until its content arrives, and counts the cards and the gaps", () => {
    const running = surveyTabs(survey({ status: "running" }));
    expect(running.filter((tab) => !tab.disabled).map((tab) => tab.id)).toEqual(["log"]);
    const done = surveyTabs(survey({ concepts: CONCEPTS, gaps: GAPS }));
    expect(done.find((tab) => tab.id === "concepts")).toMatchObject({ disabled: false, badge: "3" });
    expect(done.find((tab) => tab.id === "gaps")).toMatchObject({ disabled: false, badge: "2" });
    expect(done.find((tab) => tab.id === "taste")).toMatchObject({ disabled: true, badge: null });
  });
});

describe("tabNo", () => {
  it("numbers a section by its tab's place in the bar", () => {
    expect(tabNo("explore", "concepts")).toBe("01");
    expect(tabNo("open", "concepts")).toBe("02");
    expect(tabNo("improve", "log")).toBe("05");
  });
});

describe("hashTab", () => {
  it("reads a tab from the address, and an older link's section too", () => {
    expect(hashTab("#concepts")).toBe("concepts");
    expect(hashTab("#s-block")).toBe("area");
    expect(hashTab("")).toBeNull();
    expect(hashTab("#nowhere")).toBeNull();
    expect(hashTab("#%E0%A4%A")).toBeNull();
  });
});

describe("openingTab", () => {
  it("opens a running survey on its log, which is all it has yet", () => {
    expect(openingTab(survey({ status: "running", gaps: GAPS }), "")).toBe("log");
  });

  it("opens a finished survey on its answer", () => {
    const done = survey({ status: "complete", intent: "open", verdict: VERDICT, concepts: CONCEPTS, gaps: GAPS });
    expect(answerTab(done)).toBe("verdict");
    expect(openingTab(done, "")).toBe("verdict");
    expect(openingTab(survey({ status: "complete", gaps: GAPS }), "")).toBe("gaps");
  });

  it("opens on the tab its link names when the survey has it", () => {
    const done = survey({ status: "complete", concepts: CONCEPTS, gaps: GAPS });
    expect(openingTab(done, "#gaps")).toBe("gaps");
    expect(openingTab(done, "#taste")).toBe("concepts");
  });
});

describe("nextAction", () => {
  it("sends the evidence back to what the owner can act on", () => {
    expect(nextAction("explore")).toMatchObject({ tab: "concepts", label: "See the concepts", gate: "designs" });
    expect(nextAction("open").tab).toBe("concepts");
    expect(nextAction("improve")).toMatchObject({ tab: "improve", label: "See what to change", gate: "moves" });
  });
});
