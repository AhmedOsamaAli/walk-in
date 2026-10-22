import { createContext } from "react";

/**
 * True while the survey on screen was restored from its link, or brought back by Back or Forward, rather than streamed
 * here: it appears as it ended, so nothing on it counts up or slides in again.
 */
export const Settled = createContext(false);

export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? "auto" : "smooth";
}

/** Runs a DOM update inside a view transition when the browser has them and motion is welcome. */
export function withViewTransition(update: () => void): void {
  const doc: Partial<Pick<Document, "startViewTransition">> = document;
  if (prefersReducedMotion() || !doc.startViewTransition) {
    update();
    return;
  }
  const transition = doc.startViewTransition(update);
  // A skipped or timed-out transition still applies the update, so it is not an error.
  for (const promise of [transition.ready, transition.finished, transition.updateCallbackDone]) {
    promise.catch(() => undefined);
  }
}
