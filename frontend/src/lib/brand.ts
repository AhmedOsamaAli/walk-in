import type { SurveyStatus } from "../state/survey";

/** The mark tells the survey's story: resting on the brief, walking while it runs, arrived when it is done. */
export type MarkState = "rest" | "walking" | "arrived" | "stopped";

export const MARK_STEPS = 4;

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
