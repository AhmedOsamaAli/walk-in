/* The survey's journey (LiveStatus.tsx, the result sections and the design sheet): where a finished survey sends the
   owner first, how a "next" control takes them there, and what the tab's title says to an owner waiting in another tab. */
import type { MouseEvent } from "react";
import type { Intent } from "../api/types";
import type { SurveyState, SurveyStatus } from "../state/survey";
import { placeConcepts } from "./concepts";
import { scrollBehavior } from "./motion";
import { isPlainClick } from "./navigation";
import type { SectionId } from "./sections";

export interface ResultLink {
  /** The section it goes to. */
  id: SectionId;
  /** What waits there, named for what the owner asked: "See the 3 concepts". */
  label: string;
}

type Results = Pick<SurveyState, "intent" | "verdict" | "improve" | "concepts" | "gaps">;

/**
 * The result a finished survey points to first: the verdict on the owner's idea, what to change at their place, or the
 * concepts, counted as the section shows them. Without them, what is missing; null when the survey found nothing.
 */
export function firstResult({ intent, verdict, improve, concepts, gaps }: Results): ResultLink | null {
  if (intent === "open" && verdict) return { id: "s-verdict", label: "See the verdict" };
  if (intent === "improve" && improve) return { id: "s-improve", label: "See what to change" };
  const count = placeConcepts(concepts?.concepts ?? []).length;
  if (count) return { id: "s-concepts", label: count === 1 ? "See the concept" : `See the ${count} concepts` };
  return gaps ? { id: "s-gaps", label: "See what's missing" } : null;
}

/** The section that follows the gaps, by what the owner asked: the verdict on their idea, what to change, or concepts. */
export function afterGaps(intent: Intent): ResultLink {
  if (intent === "open") return { id: "s-verdict", label: "See the verdict on your idea" };
  if (intent === "improve") return { id: "s-improve", label: "See what to change" };
  return { id: "s-concepts", label: "See the concepts" };
}

/** What to do after a survey stopped: Back to the brief, which keeps everything it was run with. */
export function stoppedNext(found: boolean): string {
  return found
    ? "What it found is below. Your brief is kept, so you can try again."
    : "Your brief is kept, so you can try again.";
}

export const APP_TITLE = "Walk-in";

/**
 * The tab's title: "Surveying…" while the survey runs; how it ended while the owner has not seen it yet, because it
 * ended while the tab was hidden; the app's own name otherwise.
 */
export function tabTitle(status: SurveyStatus, unseen: boolean): string {
  if (status === "running") return `Surveying… · ${APP_TITLE}`;
  if (unseen && status === "complete") return `✓ Results ready · ${APP_TITLE}`;
  if (unseen && status === "failed") return `Survey stopped · ${APP_TITLE}`;
  return APP_TITLE;
}

/** The space the sticky bars take at the top of the window, as the page's scroll padding allows for them. */
export function stickyTop(): number {
  return Number.parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
}

/**
 * Brings a section's top into view under the sticky bars, smoothly unless motion is reduced, and moves focus to its
 * heading, so a screen reader reads on from there. The heading takes focus without taking a place in the Tab order.
 * Returns false when the section is not on the page.
 */
export function goToSection(id: SectionId): boolean {
  const section = document.getElementById(id);
  if (!section) return false;
  const heading = section.querySelector<HTMLElement>("h2") ?? section;
  if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
  section.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  heading.focus({ preventScroll: true });
  return true;
}

/**
 * A section's "next" link (href="#s-…"): a plain click goes to the section as goToSection does, without adding to the
 * history; a modified click, or a section not on the page, is left to the browser.
 */
export function toSection(id: SectionId) {
  return (event: MouseEvent<HTMLAnchorElement>): void => {
    if (isPlainClick(event) && goToSection(id)) event.preventDefault();
  };
}

/**
 * For a sheet that scrolls on its own, such as the design sheet: brings a heading to the top of the box it scrolls in,
 * smoothly unless motion is reduced, and moves focus to it. Nothing else on the page scrolls.
 */
export function goToInBox(heading: HTMLElement, box: HTMLElement, gap = 24): void {
  const top = box.scrollTop + heading.getBoundingClientRect().top - box.getBoundingClientRect().top - gap;
  box.scrollTo({ top: Math.max(0, top), behavior: scrollBehavior() });
  if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
  heading.focus({ preventScroll: true });
}
