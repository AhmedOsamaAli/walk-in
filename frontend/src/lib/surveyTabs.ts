/* The survey page's tabs (App.tsx): the answer first, then the evidence, the log last. Every tab is there from the start
   of a survey, dimmed until its content arrives; the page never changes tab by itself. */
import type { Intent } from "../api/types";
import type { SurveyState } from "../state/survey";
import { placeConcepts } from "./concepts";
import { firstResult } from "./journey";
import type { SectionId } from "./sections";
import { shownTab, type TabItem } from "./tabs";

export type SurveyTab = "verdict" | "concepts" | "improve" | "gaps" | "area" | "taste" | "log";

const ORDER: Record<Intent, readonly SurveyTab[]> = {
  explore: ["concepts", "gaps", "area", "taste", "log"],
  open: ["verdict", "concepts", "gaps", "area", "taste", "log"],
  improve: ["improve", "gaps", "area", "taste", "log"],
};

const LABELS: Record<SurveyTab, string> = {
  verdict: "Verdict",
  concepts: "Concepts",
  improve: "What to change",
  gaps: "Gaps",
  area: "The area",
  taste: "Taste",
  log: "Log",
};

/** The section each tab shows. */
export const TAB_SECTIONS: Record<SurveyTab, SectionId> = {
  verdict: "s-verdict",
  concepts: "s-concepts",
  improve: "s-improve",
  gaps: "s-gaps",
  area: "s-block",
  taste: "s-taste",
  log: "s-log",
};

const TABS = Object.keys(TAB_SECTIONS) as SurveyTab[];

/** The tab that shows a section. */
export const tabOf = (section: SectionId): SurveyTab => TABS.find((tab) => TAB_SECTIONS[tab] === section) ?? "log";

type Content = Pick<SurveyState, "intent" | "verdict" | "concepts" | "improve" | "gaps" | "block" | "taste">;

function arrived(tab: SurveyTab, survey: Content): boolean {
  if (tab === "verdict") return survey.verdict !== null;
  if (tab === "concepts") return survey.concepts !== null;
  if (tab === "improve") return survey.improve !== null;
  if (tab === "gaps") return survey.gaps !== null;
  if (tab === "area") return survey.block !== null;
  if (tab === "taste") return survey.taste !== null;
  return true;
}

const count = (n: number): string | null => (n ? String(n) : null);

/** A count where it helps choose the tab: the concepts' cards, the gaps ranked, the moves to make. */
function badge(tab: SurveyTab, { concepts, gaps, improve }: Content): string | null {
  if (tab === "concepts") return count(placeConcepts(concepts?.concepts ?? []).length);
  if (tab === "gaps") return count(gaps?.length ?? 0);
  if (tab === "improve" && improve && !("note" in improve)) return count(improve.moves.length);
  return null;
}

export interface SurveyTabItem extends TabItem {
  id: SurveyTab;
}

/**
 * The tabs of a survey of this intent, in order, each dimmed until its content arrives; while the survey runs, those
 * still to come say they are on their way.
 */
export function surveyTabs(survey: Content & Partial<Pick<SurveyState, "status">>): SurveyTabItem[] {
  return ORDER[survey.intent].map((id) => {
    const disabled = !arrived(id, survey);
    return { id, label: LABELS[id], disabled, pending: disabled && survey.status === "running", badge: badge(id, survey) };
  });
}

/** A tab's place in the bar as its section's head numbers it: "01" for the first. */
export function tabNo(intent: Intent, tab: SurveyTab): string {
  return String(ORDER[intent].indexOf(tab) + 1).padStart(2, "0");
}

const isSurveyTab = (name: string): name is SurveyTab => (TABS as string[]).includes(name);

/** The tab an address's hash names: "#concepts", or an older link's section, "#s-concepts"; null for none. */
export function hashTab(hash: string): SurveyTab | null {
  let name = hash.replace(/^#/, "");
  try {
    name = decodeURIComponent(name);
  } catch {
    return null;
  }
  if (isSurveyTab(name)) return name;
  return TABS.find((tab) => TAB_SECTIONS[tab] === name) ?? null;
}

/** The tab that holds what the owner asked for once the survey is complete: the verdict, what to change, or concepts. */
export function answerTab(survey: Content): SurveyTab | null {
  const result = firstResult(survey);
  return result ? tabOf(result.id) : null;
}

/**
 * The tab a survey opens on when it appears: the one its link names, if it has it; else, while it runs, the log, which
 * is all it has yet; once it has ended, its answer.
 */
export function openingTab(survey: Content & Pick<SurveyState, "status">, hash: string): SurveyTab {
  const items = surveyTabs(survey);
  const asked = hashTab(hash);
  if (asked && items.some((item) => item.id === asked && !item.disabled)) return asked;
  if (survey.status === "running") return "log";
  return (answerTab(survey) ?? shownTab(items, null) ?? "log") as SurveyTab;
}
