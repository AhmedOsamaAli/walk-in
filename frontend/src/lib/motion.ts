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
