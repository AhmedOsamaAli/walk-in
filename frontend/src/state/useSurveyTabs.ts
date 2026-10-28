/* The survey's tabs: the one on show, the ones left since they were last shown (what they hold does not slide in again
   when they come back), and whether the owner has opened the answer since the survey completed. */
import { useState } from "react";
import { flushSync } from "react-dom";
import { firstResult, focusHeading, revealPanel, type ResultLink } from "../lib/journey";
import { answerTab, hashTab, openingTab, SURVEY_TABS_ID, surveyTabs, type SurveyTab, type SurveyTabItem } from "../lib/surveyTabs";
import { panelId, shownTab } from "../lib/tabs";
import type { SurveyState } from "./survey";

export interface SurveyTabs {
  tabs: SurveyTabItem[];
  selected: SurveyTab;
  left: { run: number; tabs: SurveyTab[] };
  /** The tab with the answer, once the survey is complete. */
  answer: SurveyTab | null;
  /** Where the status bar sends the owner once the survey is done, until they have opened the answer. */
  result: ResultLink | null;
  /**
   * Shows a tab and names it in the address (#concepts), so its link opens on it. When the page had scrolled past the
   * panel's top, it comes back into view under the pinned bars; `focus` moves focus to its heading.
   */
  showTab: (id: SurveyTab, focus: boolean) => void;
  /** Back or Forward moved only the hash, to a tab's name (#gaps): the survey shows that tab when it has it. */
  followHash: (hash: string) => void;
}

/**
 * A survey that appears opens on the tab its link names, else its log while it runs, else its answer; after that only
 * the owner changes tab. `surveying`: the survey is on screen.
 */
export function useSurveyTabs(survey: SurveyState, surveying: boolean): SurveyTabs {
  /** The tab, for the run it was chosen in. */
  const [tab, setTab] = useState<{ run: number; id: SurveyTab } | null>(null);
  const [left, setLeft] = useState<{ run: number; tabs: SurveyTab[] }>({ run: 0, tabs: [] });
  /** The run whose answer the owner has opened since it completed: the status bar stops offering it. */
  const [answered, setAnswered] = useState<number | null>(null);

  const tabs = surveyTabs(survey);
  if (surveying && tab?.run !== survey.run) setTab({ run: survey.run, id: openingTab(survey, window.location.hash) });
  const selected = (shownTab(tabs, tab?.run === survey.run ? tab.id : null) ?? "log") as SurveyTab;
  const answer = survey.status === "complete" ? answerTab(survey) : null;
  if (surveying && answer !== null && selected === answer && answered !== survey.run) setAnswered(survey.run);
  const result = answer !== null && answered !== survey.run ? firstResult(survey) : null;

  function showTab(id: SurveyTab, focus: boolean) {
    const from = selected;
    flushSync(() => {
      setTab({ run: survey.run, id });
      if (from !== id) {
        setLeft((now) => ({ run: survey.run, tabs: [...(now.run === survey.run ? now.tabs : []), from] }));
      }
    });
    window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}#${id}`);
    const panel = document.getElementById(panelId(SURVEY_TABS_ID, id));
    const bar = document.querySelector<HTMLElement>(".survey-tabs");
    if (!panel) return;
    if (bar) revealPanel(panel, bar);
    if (focus) focusHeading(panel);
  }

  function followHash(hash: string) {
    const asked = hashTab(hash);
    if (surveying && asked && asked !== selected && tabs.some((item) => item.id === asked && !item.disabled)) {
      showTab(asked, false);
    }
  }

  return { tabs, selected, left, answer, result, showTab, followHash };
}
