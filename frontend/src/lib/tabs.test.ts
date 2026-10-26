import { describe, expect, it } from "vitest";
import { nextTab, pagerOf, shownTab, type TabItem } from "./tabs";

const items: TabItem[] = [
  { id: "concepts", label: "Concepts" },
  { id: "gaps", label: "Gaps" },
  { id: "area", label: "The area", disabled: true },
  { id: "taste", label: "Taste" },
  { id: "log", label: "Log" },
];

describe("nextTab", () => {
  it("moves to the next or previous selectable tab, wrapping round and skipping those not ready", () => {
    expect(nextTab(items, "gaps", "ArrowRight")).toBe("taste");
    expect(nextTab(items, "taste", "ArrowLeft")).toBe("gaps");
    expect(nextTab(items, "log", "ArrowRight")).toBe("concepts");
    expect(nextTab(items, "concepts", "ArrowLeft")).toBe("log");
  });

  it("goes to the first or last selectable tab with Home and End", () => {
    expect(nextTab(items, "taste", "Home")).toBe("concepts");
    expect(nextTab(items, "concepts", "End")).toBe("log");
  });

  it("does nothing for other keys, or when no other tab can be selected", () => {
    expect(nextTab(items, "gaps", "ArrowDown")).toBeNull();
    expect(nextTab(items, "concepts", "Home")).toBeNull();
    expect(nextTab([{ id: "log", label: "Log" }], "log", "ArrowRight")).toBeNull();
  });
});

describe("shownTab", () => {
  it("shows the tab asked for while it can be shown, else the first that can", () => {
    expect(shownTab(items, "taste")).toBe("taste");
    expect(shownTab(items, "area")).toBe("concepts");
    expect(shownTab(items, null)).toBe("concepts");
    expect(shownTab([{ id: "x", label: "X", disabled: true }], "x")).toBeNull();
  });
});

describe("pagerOf", () => {
  const ids = (pager: ReturnType<typeof pagerOf>) => [pager.previous?.id ?? null, pager.next?.id ?? null, pager.wraps];

  it("leads on to the next tab and back to the one before, passing over tabs not ready", () => {
    expect(ids(pagerOf(items, "concepts"))).toEqual([null, "gaps", false]);
    expect(ids(pagerOf(items, "gaps"))).toEqual(["concepts", "taste", false]);
    expect(ids(pagerOf(items, "taste"))).toEqual(["gaps", "log", false]);
  });

  it("leads from the last tab back to the first", () => {
    expect(ids(pagerOf(items, "log"))).toEqual(["taste", "concepts", true]);
  });

  it("offers nothing with a single tab, or for a tab that cannot be shown", () => {
    expect(ids(pagerOf([{ id: "log", label: "Log" }], "log"))).toEqual([null, null, false]);
    expect(ids(pagerOf(items, "area"))).toEqual([null, null, false]);
  });
});
