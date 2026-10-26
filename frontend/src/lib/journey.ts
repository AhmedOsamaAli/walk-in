/* The survey's journey (LiveStatus.tsx, the result tabs and the design sheet): where a finished survey sends the owner
   first, how a tab switch shows the next part, and what the tab's title says to an owner waiting in another tab. */
import type { SurveyState, SurveyStatus } from "../state/survey";
import { placeConcepts } from "./concepts";
import { scrollBehavior } from "./motion";
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

/** What to do after a survey stopped: Back to the brief, which keeps everything it was run with. */
export function stoppedNext(found: boolean): string {
  return found
    ? "What it found is in the tabs below. Your brief is kept, so you can try again."
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

/**
 * After a tab switch, the new panel's top in view under the pinned bars: when the page (or the sheet, `box`) had
 * scrolled past it, it scrolls back to it, smoothly unless motion is reduced; otherwise nothing moves.
 */
export function revealPanel(panel: HTMLElement, bar: HTMLElement, box?: HTMLElement): void {
  const gap = panel.getBoundingClientRect().top - bar.getBoundingClientRect().bottom;
  if (gap >= 0) return;
  (box ?? window).scrollBy({ top: gap, behavior: scrollBehavior() });
}

/** Moves focus to a panel's heading, which takes it without taking a place in the Tab order. */
export function focusHeading(panel: HTMLElement): void {
  const heading = panel.querySelector<HTMLElement>("h2, h3");
  if (!heading) return;
  if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1");
  heading.focus({ preventScroll: true });
}