/** Lines the survey log shows while folded: the newest, so a running survey's latest step stays in view. */
export const FOLDED_LINES = 4;

/** The log newest first, cut to its newest `keep` lines while folded; `hidden` counts the lines left out. */
export function logView<T>(lines: readonly T[], open: boolean, keep = FOLDED_LINES): { shown: T[]; hidden: number } {
  const newestFirst = lines.toReversed();
  if (open || newestFirst.length <= keep) return { shown: newestFirst, hidden: 0 };
  return { shown: newestFirst.slice(0, keep), hidden: newestFirst.length - keep };
}
