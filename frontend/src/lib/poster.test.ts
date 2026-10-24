import { describe, expect, it } from "vitest";
import { fitLines, layoutPoster, POSTER_H, POSTER_M, POSTER_W, posterAreaLine, roughMeasure, type PosterText } from "./poster";

const TEXT: PosterText = {
  name: "Golden Hour",
  tagline: null,
  headline: "Bakery without crossing town",
  subline: "The only bakery within a 10-minute walk.",
  hours: "Mon–Thu 11 am–10 pm · Fri–Sat 11 am–11:30 pm · Sun 11 am–10 pm",
  proof: "Qloo lists no bakery inside the walk, and OpenStreetMap shows none either.",
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
    expect(layout.qr && layout.qr.x + layout.qr.size).toBe(POSTER_W - POSTER_M);
    // With a QR code, the hours run under the subline, in its column.
    expect(layout.hoursX).toBe(POSTER_M);
    expect(layout.hoursBox).toBeNull();
    expect(layout.hoursLabelY).toBeGreaterThan(layout.subline?.y.at(-1) ?? 0);
  });

  it("puts the hours in the QR code's place on a poster without one", () => {
    const layout = layoutPoster(TEXT, roughMeasure, { qr: false });
    const box = layout.hoursBox;
    expect(layout.qr).toBeNull();
    expect(box).not.toBeNull();
    if (!box || !layout.hours || !layout.subline || layout.hoursLabelY === null) return;
    // The box ends at the right margin, starts where the code would, and holds every line of the hours.
    expect(box.x + box.width).toBe(POSTER_W - POSTER_M);
    expect(box.y).toBe(layout.bandTop + 24);
    expect(layout.hoursX).toBeGreaterThan(box.x);
    expect(layout.hoursLabelY).toBeGreaterThan(box.y);
    expect(layout.hours.lines).toEqual(["Mon–Thu 11 am–10 pm", "Fri–Sat 11 am–11:30 pm", "Sun 11 am–10 pm"]);
    for (const width of layout.hours.widths) expect(layout.hoursX + width).toBeLessThanOrEqual(box.x + box.width);
    expect(layout.hours.y.at(-1)).toBeLessThan(box.y + box.height);
    // The subline keeps the left column, clear of the box, and the box clears the proof at the foot.
    for (const width of layout.subline.widths) expect(POSTER_M + width).toBeLessThan(box.x);
    expect(box.y + box.height).toBeLessThan(layout.proof?.y[0] ?? POSTER_H);
  });

  it("gives the subline the whole band when there is neither a QR code nor hours beside it", () => {
    const long = "Croissants and kouign-amann, the morning bread people here cross town for.";
    const alone = layoutPoster({ ...TEXT, subline: long, hours: null }, roughMeasure, { qr: false });
    const beside = layoutPoster({ ...TEXT, subline: long, hours: null }, roughMeasure);
    expect(alone.hoursBox).toBeNull();
    expect(Math.max(...(alone.subline?.widths ?? []))).toBeGreaterThan(INNER - 148 - 28);
    expect(alone.subline?.lines.length).toBeLessThan(beside.subline?.lines.length ?? 0);
    // Hours without a subline stay on the left, where the eye starts.
    const hoursOnly = layoutPoster({ ...TEXT, subline: null }, roughMeasure, { qr: false });
    expect(hoursOnly.hoursBox).toBeNull();
    expect(hoursOnly.hoursX).toBe(POSTER_M);
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

describe("the line over the poster's map", () => {
  it("says the blue line is a walk away, or within a drive", () => {
    expect(posterAreaLine("10-minute walk")).toBe("EVERYONE INSIDE THE BLUE LINE IS A 10-MINUTE WALK AWAY");
    expect(posterAreaLine("30-minute drive")).toBe("EVERYONE INSIDE THE BLUE LINE IS WITHIN A 30-MINUTE DRIVE");
    expect(posterAreaLine("25 km drive")).toBe("EVERYONE INSIDE THE BLUE LINE IS WITHIN A 25 KM DRIVE");
  });

  it("puts 'an' before a number said with a vowel", () => {
    expect(posterAreaLine("8-minute walk")).toBe("EVERYONE INSIDE THE BLUE LINE IS AN 8-MINUTE WALK AWAY");
    expect(posterAreaLine("11 km drive")).toBe("EVERYONE INSIDE THE BLUE LINE IS WITHIN AN 11 KM DRIVE");
    expect(posterAreaLine("18-minute drive")).toBe("EVERYONE INSIDE THE BLUE LINE IS WITHIN AN 18-MINUTE DRIVE");
    expect(posterAreaLine("80 km drive")).toBe("EVERYONE INSIDE THE BLUE LINE IS WITHIN AN 80 KM DRIVE");
    expect(posterAreaLine("1.5 km drive")).toBe("EVERYONE INSIDE THE BLUE LINE IS WITHIN A 1.5 KM DRIVE");
    expect(posterAreaLine("15-minute walk")).toBe("EVERYONE INSIDE THE BLUE LINE IS A 15-MINUTE WALK AWAY");
  });
});
