import { describe, expect, it } from "vitest";
import { FOLDED_LINES, logView } from "./log";

describe("logView", () => {
  const lines = Array.from({ length: 10 }, (_, i) => i + 1);

  it("shows only the newest lines while folded, newest first, and counts the rest", () => {
    const { shown, hidden } = logView(lines, false);
    expect(shown).toEqual([10, 9, 8, 7].slice(0, FOLDED_LINES));
    expect(hidden).toBe(lines.length - FOLDED_LINES);
  });

  it("shows every line once opened", () => {
    expect(logView(lines, true)).toEqual({ shown: lines.toReversed(), hidden: 0 });
  });

  it("never folds a log short enough to show whole", () => {
    expect(logView([1, 2, 3], false)).toEqual({ shown: [3, 2, 1], hidden: 0 });
    expect(logView([], false)).toEqual({ shown: [], hidden: 0 });
  });
});
