import { describe, expect, it } from "vitest";
import { homeMove, isPlainClick } from "./navigation";

describe("homeMove", () => {
  it("goes back to the top of the brief, keeping it, when the brief is showing", () => {
    expect(homeMove("brief")).toBe("top");
  });

  it("starts over on a fresh brief from a survey or a survey's link still loading", () => {
    expect(homeMove("survey")).toBe("fresh");
    expect(homeMove("opening")).toBe("fresh");
  });

  it("shows the brief as it was left from another page", () => {
    expect(homeMove("page")).toBe("brief");
  });
});

describe("isPlainClick", () => {
  const click = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };

  it("handles a plain primary click in place", () => {
    expect(isPlainClick(click)).toBe(true);
  });

  it("leaves modified, middle and already handled clicks to the browser", () => {
    expect(isPlainClick({ ...click, metaKey: true })).toBe(false);
    expect(isPlainClick({ ...click, ctrlKey: true })).toBe(false);
    expect(isPlainClick({ ...click, shiftKey: true })).toBe(false);
    expect(isPlainClick({ ...click, altKey: true })).toBe(false);
    expect(isPlainClick({ ...click, button: 1 })).toBe(false);
    expect(isPlainClick({ ...click, defaultPrevented: true })).toBe(false);
  });
});
