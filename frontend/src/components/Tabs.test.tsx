import { Children, isValidElement, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TabItem } from "../lib/tabs";
import { TabPager } from "./Tabs";

const ITEMS: TabItem[] = [
  { id: "concepts", label: "Concepts", teaser: "Business concepts ranked by the evidence." },
  { id: "gaps", label: "Gaps", teaser: "Place types people here love that the area is short of." },
  { id: "area", label: "The area", disabled: true, teaser: "What is already inside the area." },
  { id: "taste", label: "Taste" },
  { id: "log", label: "Log", teaser: "Each step of the survey." },
];

const pager = (current: string, items = ITEMS) =>
  renderToStaticMarkup(<TabPager items={items} current={current} onSelect={() => undefined} />);

interface ButtonProps {
  children?: ReactNode;
  onClick?: () => void;
}

/** The buttons in an element tree, in order. */
function buttonsIn(node: ReactNode): ReactElement<ButtonProps>[] {
  return Children.toArray(node).flatMap((child) => {
    if (!isValidElement<ButtonProps>(child)) return [];
    return child.type === "button" ? [child] : buttonsIn(child.props.children);
  });
}

describe("TabPager", () => {
  it("leads on with a card: Next to discover, the next tab's name, what it shows, and an arrow", () => {
    expect(pager("concepts")).toBe(
      '<nav class="tab-pager" aria-label="Next and previous">' +
        '<button type="button" class="tab-pager-next tab-pager-card"><span class="tab-pager-text">' +
        '<span class="tab-pager-eyebrow mono">Next to discover<span class="sr-only">: </span></span>' +
        '<span class="tab-pager-label">Gaps</span>' +
        '<span class="tab-pager-teaser"><span class="sr-only">. </span>Place types people here love that the area is short of.</span>' +
        '</span><span class="tab-pager-arrow" aria-hidden="true">→</span></button></nav>',
    );
  });

  it("keeps the way back to the tab before, passes over a tab not ready, and leaves out a teaser it has not got", () => {
    const html = pager("gaps");
    expect(html).toMatch(/^<nav [^>]*><button type="button" class="tab-pager-back"><span aria-hidden="true">←<\/span> Concepts<\/button>/);
    expect(html).toContain('<span class="tab-pager-label">Taste</span></span>');
    expect(html).not.toContain("tab-pager-teaser");
  });

  it("goes back to the first tab from the last as before: a pill, not something new to discover", () => {
    const html = pager("log");
    expect(html).toContain('<button type="button" class="tab-pager-next">Back to Concepts</button>');
    expect(html).not.toContain("Next to discover");
  });

  it("draws nothing where there is no other tab", () => {
    expect(pager("log", [{ id: "log", label: "Log", teaser: "Each step of the survey." }])).toBe("");
  });

  it("shows the tab each button names", () => {
    const clicks = (current: string) => {
      const shown: string[] = [];
      const nav = TabPager({
        items: ITEMS,
        current,
        onSelect: (id) => {
          shown.push(id);
        },
      });
      for (const button of buttonsIn(nav)) button.props.onClick?.();
      return shown;
    };
    expect(clicks("concepts")).toEqual(["gaps"]);
    expect(clicks("gaps")).toEqual(["concepts", "taste"]);
    expect(clicks("log")).toEqual(["taste", "concepts"]);
  });
});
