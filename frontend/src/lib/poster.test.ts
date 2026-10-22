import { describe, expect, it } from "vitest";
import { fitLines, layoutPoster, POSTER_H, POSTER_M, POSTER_W, roughMeasure, type PosterText } from "./poster";

const TEXT: PosterText = {
  name: "Golden Hour",
  tagline: null,
  headline: "Bakery without crossing town",
  subline: "The only $$$ bakery within a 10-minute walk.",
  hours: "Mon–Thu 11 am–10 pm · Fri–Sat 11 am–11:30 pm · Sun 11 am–10 pm",
  proof: "None of the 2 bakeries inside the walk that list a price is $$$; 2 of the bakeries people here love are.",
};
const INNER = POSTER_W - 2 * POSTER_M;

describe("poster layout", () => {
  it("sets every line inside the margins, top to bottom without overlaps", () => {
    const layout = layoutPoster(TEXT, roughMeasure);
    expect(layout.name.lines).toEqual(["Golden Hour"]);
    expect(layout.name.size).toBeGreaterThanOrEqual(62);
    for (const block of [layout.name, layout.headline, layout.subline, layout.hours, layout.proof]) {
      for (const width of block?.widths ?? []) expect(width).toBeLessThanOrEqual(INNER);
    }
    const nameEnd = layout.name.y.at(-1) ?? 0;
    const headline = layout.headline;
    expect(headline?.y[0]).toBeGreaterThan(nameEnd);
    expect(layout.map.y).toBeGreaterThan(headline?.y.at(-1) ?? 0);
    expect(layout.map.y + layout.map.height).toBeLessThan(layout.bandTop);
    expect(layout.map.height).toBeGreaterThanOrEqual(170);
    expect(layout.subline?.y[0]).toBeGreaterThan(layout.bandTop);
    expect(layout.hours?.lines).toEqual(["Mon–Thu 11 am–10 pm", "Fri–Sat 11 am–11:30 pm", "Sun 11 am–10 pm"]);
    expect(layout.proof?.y.at(-1)).toBeLessThan(POSTER_H);
    expect(layout.qr.x + layout.qr.size).toBe(POSTER_W - POSTER_M);
  });

  it("breaks a long name into two balanced lines", () => {
    const layout = layoutPoster({ ...TEXT, name: "The Kouign Amann Society of East Austin" }, roughMeasure);
    expect(layout.name.lines).toHaveLength(2);
    for (const width of layout.name.widths) expect(width).toBeLessThanOrEqual(INNER + 0.5);
  });

  it("leaves out what the kit does not have", () => {
    const layout = layoutPoster({ name: "Seafood", tagline: null, headline: null, subline: null, hours: null, proof: null }, roughMeasure);
    expect([layout.headline, layout.subline, layout.hours, layout.proof, layout.tagline]).toEqual([null, null, null, null, null]);
    expect(layout.map.height).toBeGreaterThan(300);
  });

  it("keeps lines within a width and cuts the last one with an ellipsis", () => {
    const measure = (line: string) => line.length;
    expect(fitLines("one two three four", 9, measure, 3)).toEqual(["one two", "three", "four"]);
    expect(fitLines("one two three four five six", 9, measure, 2)).toEqual(["one two", "three…"]);
    expect(fitLines("", 9, measure, 2)).toEqual([]);
  });
});
