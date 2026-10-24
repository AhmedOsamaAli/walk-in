import type { SurveyStatus } from "../state/survey";
import type { HomeMove } from "./navigation";

/** The mark tells the survey's story: resting on the brief, walking while it runs, arrived when it is done. */
export type MarkState = "rest" | "walking" | "arrived" | "stopped";

export const MARK_STEPS = 4;

/**
 * How long the walk-in plays, in ms: the four steps land, the door shuts behind the last one, swings open and the light
 * spills out (the .bm-* animations in layout.css, the spill ending last at 2.05 s).
 */
export const WALK_IN_MS = 2100;

/** The mark's accessible name: what clicking it does from where the window is. */
export function markLabel(move: HomeMove): string {
  if (move === "top") return "Walk-in, back to the top";
  if (move === "fresh") return "Walk-in, start over";
  return "Walk-in, back to the brief";
}

/**
 * Whether the mark plays its walk again: never with reduced motion; on every click or tap, since phones have no hover;
 * on a mouse hover or keyboard focus only once the last walk has ended, so a pointer crossing its edge does not restart
 * it.
 */
export function replays(cause: "click" | "preview", reducedMotion: boolean, sinceLastMs: number): boolean {
  if (reducedMotion) return false;
  return cause === "click" || sinceLastMs >= WALK_IN_MS;
}

export function markState(surveying: boolean, status: SurveyStatus): MarkState {
  if (!surveying) return "rest";
  if (status === "complete") return "arrived";
  if (status === "failed") return "stopped";
  return "walking";
}

/** How many footsteps are lit: one for each fifth of the survey, all of them once the door opens. */
export function litSteps(state: MarkState, progress: number): number {
  if (state === "rest" || state === "arrived") return MARK_STEPS;
  return Math.max(0, Math.min(MARK_STEPS, Math.floor(progress * (MARK_STEPS + 1))));
}
