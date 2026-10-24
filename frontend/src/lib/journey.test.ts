import { describe, expect, it } from "vitest";
import type { Concept, ConceptsPayload, Verdict } from "../api/types";
import { initialSurvey, type SurveyState } from "../state/survey";
import { APP_TITLE, firstResult, stoppedNext, tabTitle } from "./journey";

const concept = (name: string, wildcard = false): Concept => ({ name, genre: "Coffee shop", gap_score: wildcard ? null : 60, wildcard });

const CONCEPTS: ConceptsPayload = { concepts: [concept("Tidewater"), concept("Kahwa Corner"), concept("Crumb & Chapter", true)] };

const VERDICT: Verdict = { query: "Coffee shop", found: true, level: "strong", headline: "A strong fit.", evidence: [] };

function survey(patch: Partial<SurveyState>): SurveyState {
  return { ...initialSurvey, status: "complete", gaps: [], ...patch };
}

describe("firstResult", () => {
  it("sends an idea under test to its verdict", () => {
    expect(firstResult(survey({ intent: "open", verdict: VERDICT, concepts: CONCEPTS }))).toEqual({
      id: "s-verdict",
      label: "See the verdict",
    });
  });

  it("sends a place under review to what to change", () => {
    expect(firstResult(survey({ intent: "improve", improve: { note: "Not on Qloo." } }))).toEqual({
      id: "s-improve",
      label: "See what to change",
    });
  });

  it("counts every card the concepts section shows, the wild card included", () => {
    expect(firstResult(survey({ intent: "explore", concepts: CONCEPTS }))).toEqual({
      id: "s-concepts",
      label: "See the 3 concepts",
    });
    expect(firstResult(survey({ concepts: { concepts: [concept("Tidewater")] } }))?.label).toBe("See the concept");
  });

  it("falls back to the concepts when an idea or a place has no answer, and to the gaps without concepts", () => {
    expect(firstResult(survey({ intent: "open", concepts: CONCEPTS }))?.id).toBe("s-concepts");
    expect(firstResult(survey({ intent: "explore", concepts: { concepts: [], note: "None fit." } }))).toEqual({
      id: "s-gaps",
      label: "See what's missing",
    });
    expect(firstResult(survey({ intent: "improve" }))?.id).toBe("s-gaps");
  });

  it("points nowhere when the survey found nothing to show", () => {
    expect(firstResult(survey({ gaps: null }))).toBeNull();
  });
});

describe("stoppedNext", () => {
  it("says what to do after a stop, and that what was found stays", () => {
    expect(stoppedNext(false)).toBe("Choose New survey to try again: your brief is kept.");
    expect(stoppedNext(true)).toMatch(/^What it found is below\. Choose New survey/);
  });
});

describe("tabTitle", () => {
  it("says the survey runs, whether or not the tab is in view", () => {
    expect(tabTitle("running", false)).toBe("Surveying… · Walk-in");
    expect(tabTitle("running", true)).toBe("Surveying… · Walk-in");
  });

  it("tells an owner who was away how it ended", () => {
    expect(tabTitle("complete", true)).toBe("✓ Results ready · Walk-in");
    expect(tabTitle("failed", true)).toBe("Survey stopped · Walk-in");
  });

  it("is the app's own name once the end has been seen, and before any survey", () => {
    expect(tabTitle("complete", false)).toBe(APP_TITLE);
    expect(tabTitle("failed", false)).toBe(APP_TITLE);
    expect(tabTitle("idle", true)).toBe(APP_TITLE);
    expect(APP_TITLE).toBe("Walk-in");
  });
});
