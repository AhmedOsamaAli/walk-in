import { describe, expect, it } from "vitest";
import { litSteps, markState } from "./brand";

describe("markState", () => {
  it("rests on the brief, walks while the survey runs and arrives when it is done", () => {
    expect(markState(false, "idle")).toBe("rest");
    expect(markState(false, "complete")).toBe("rest");
    expect(markState(true, "running")).toBe("walking");
    expect(markState(true, "complete")).toBe("arrived");
    expect(markState(true, "failed")).toBe("stopped");
  });
});

describe("litSteps", () => {
  it("lights one footstep for each fifth of the survey", () => {
    expect(litSteps("walking", 0)).toBe(0);
    expect(litSteps("walking", 0.19)).toBe(0);
    expect(litSteps("walking", 0.2)).toBe(1);
    expect(litSteps("walking", 0.85)).toBe(4);
    expect(litSteps("walking", 1.4)).toBe(4);
  });

  it("keeps the steps a failed survey reached, and lights all of them at rest or on arrival", () => {
    expect(litSteps("stopped", 0.45)).toBe(2);
    expect(litSteps("rest", 0)).toBe(4);
    expect(litSteps("arrived", 0.6)).toBe(4);
  });
});
