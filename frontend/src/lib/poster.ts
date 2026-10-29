/* The window poster's layout: where each line of the kit's poster goes on a portrait sheet (A-series proportions),
   from a function that measures text. Pure, so it is tested with a stand-in measure. */

export const POSTER_W = 600;
export const POSTER_H = 848;
export const POSTER_M = 44;
const INNER = POSTER_W - 2 * POSTER_M;

export type Face = "serif" | "sans" | "mono";

/** The width of `text` set in a face at a size, in poster units. */
export type Measure = (text: string, face: Face, size: number, italic?: boolean) => number;

export interface Block {
  lines: string[];
  size: number;
  /** Each line's baseline. */
  y: number[];
  /** Each line's width, for the highlighter behind a headline. */
  widths: number[];
}

export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PosterLayout {
  name: Block;
  tagline: Block | null;
  headline: Block | null;
  map: { y: number; height: number };
  bandTop: number;
  /** The Founders campaign's line in its yellow box, beside the QR code to the campaign; null without a campaign. */
  back: { box: Box; text: Block } | null;
  subline: Block | null;
  hours: Block | null;
  hoursLabelY: number | null;
  /** Where the hours and their label start. */
  hoursX: number;
  /** The box the hours sit in when they take the QR code's place; null when they run under the subline. */
  hoursBox: Box | null;
  /** The QR code's square; null for a poster without a link of the owner's to send a passer-by to. */
  qr: { x: number; y: number; size: number } | null;
  proof: Block | null;
}

export interface PosterText {
  name: string;
  tagline: string | null;
  headline: string | null;
  subline: string | null;
  hours: string | null;
  proof: string | null;
  /** The owner's open Founders campaign, in a line from its own terms ("Back it before it opens: pledge $25, …"). */
  back?: string | null;
}

/** Words broken into lines no wider than `width` when set; at most `most` lines, the last one ending in "…" if cut. */
export function fitLines(text: string, width: number, measure: (line: string) => number, most: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const trial = line ? `${line} ${word}` : word;
    if (line && measure(trial) > width) {
      lines.push(line);
      line = word;
    } else line = trial;
  }
  if (line) lines.push(line);
  if (lines.length <= most) return lines;
  const kept = lines.slice(0, most);
  let last = kept[most - 1] ?? "";
  while (last && measure(`${last}…`) > width) last = last.split(" ").slice(0, -1).join(" ");
  kept[most - 1] = `${last}…`;
  return kept;
}

/** The name in one line when it can be set large, else in two balanced lines. */
function nameLines(name: string, measure: Measure, scale: number): { lines: string[]; size: number } {
  const one = measure(name, "serif", 100);
  const single = Math.min(104, (100 * INNER) / Math.max(one, 1)) * scale;
  if (single >= 62 * scale || !name.includes(" ")) return { lines: [name], size: Math.min(single, 104) };
  const words = name.split(/\s+/);
  let best: string[] = [name];
  let widest = Infinity;
  for (let cut = 1; cut < words.length; cut += 1) {
    const pair = [words.slice(0, cut).join(" "), words.slice(cut).join(" ")];
    const width = Math.max(...pair.map((line) => measure(line, "serif", 100)));
    if (width < widest) {
      widest = width;
      best = pair;
    }
  }
  return { lines: best, size: Math.min(92, (100 * INNER) / Math.max(widest, 1)) * scale };
}

function block(lines: string[], size: number, top: number, leading: number, width: (line: string) => number): Block {
  const y = lines.map((_, index) => Math.round(top + size * 0.8 + index * size * leading));
  return { lines, size, y, widths: lines.map(width) };
}

const bottomOf = (b: Block | null, fallback: number) => (b ? (b.y.at(-1) ?? fallback) + b.size * 0.3 : fallback);

const QR_SIZE = 148;
const GUTTER = 28;
const HOURS_SIZE = 13.5;
const BOX_PAD = 16;
const BOX_MOST = 232;
export const BACK_SIZE = 17;
export const BACK_PAD = 14;
// The campaign's line is set a little heavier than the measure assumes: it keeps this much room spare.
const BACK_SLACK = 0.94;
/** Nothing in the band runs below this, clear of the proof line at the foot. */
const BAND_FLOOR = POSTER_H - 58;

/**
 * Lays the poster out; when the walk's map would be too small, the name is set smaller until it fits. Without a QR code
 * the band keeps its two columns: the subline on the left, and the hours in a box where the code would be. With a
 * Founders campaign, the campaign's line takes the top of the left column in a yellow box beside the QR code; the
 * subline follows it, smaller, and the hours only when they still fit.
 */
export function layoutPoster(text: PosterText, measure: Measure, { qr = true }: { qr?: boolean } = {}): PosterLayout {
  let layout = attempt(text, measure, 1, qr);
  for (const scale of [0.86, 0.74, 0.62]) {
    if (layout.map.height >= 170) break;
    layout = attempt(text, measure, scale, qr);
  }
  return layout;
}

function attempt(text: PosterText, measure: Measure, scale: number, withQr: boolean): PosterLayout {
  const top = 84;
  const named = nameLines(text.name, measure, scale);
  const name = block(named.lines, named.size, top, 0.98, (line) => measure(line, "serif", named.size));
  let y = bottomOf(name, top);

  let tagline: Block | null = null;
  if (text.tagline) {
    const size = 21;
    const lines = fitLines(text.tagline, INNER, (line) => measure(line, "serif", size, true), 2);
    tagline = block(lines, size, y + 10, 1.3, (line) => measure(line, "serif", size, true));
    y = bottomOf(tagline, y);
  }

  let headline: Block | null = null;
  if (text.headline) {
    let size = 38 * Math.max(scale, 0.8);
    let lines = fitLines(text.headline, INNER - 8, (line) => measure(line, "serif", size, true), 4);
    if (lines.length > 2) {
      size *= 0.84;
      lines = fitLines(text.headline, INNER - 8, (line) => measure(line, "serif", size, true), 3);
    }
    headline = block(lines, size, y + 18, 1.16, (line) => measure(line, "serif", size, true));
    y = bottomOf(headline, y);
  }

  const bandTop = POSTER_H - 236;
  const slotTop = bandTop + 24;
  const groups = (text.hours ?? "").split(" · ").filter(Boolean).slice(0, 4);
  const hoursWidth = (line: string) => measure(line, "sans", HOURS_SIZE);
  // Without a QR code, the hours take its place in a box as wide as they need, between the code's width and BOX_MOST.
  const boxed = !withQr && Boolean(text.subline) && groups.length > 0;
  const boxWidth = boxed
    ? Math.ceil(Math.min(BOX_MOST, Math.max(QR_SIZE, ...groups.map(hoursWidth).map((width) => width + 2 * BOX_PAD))))
    : 0;
  const right = withQr ? QR_SIZE : boxWidth;
  const columnWidth = right ? INNER - right - GUTTER : INNER;
  let back: PosterLayout["back"] = null;
  let bandY = bandTop + 26;
  if (text.back) {
    const width = (line: string) => measure(line, "sans", BACK_SIZE);
    const lines = fitLines(text.back, (columnWidth - 2 * BACK_PAD) * BACK_SLACK, width, 4);
    const words = block(lines, BACK_SIZE, slotTop + BACK_PAD - 2, 1.28, width);
    const bottom = Math.round(bottomOf(words, slotTop) + BACK_PAD);
    back = { box: { x: POSTER_M, y: slotTop, width: columnWidth, height: bottom - slotTop }, text: words };
    bandY = bottom + 18;
  }
  let subline: Block | null = null;
  if (text.subline) {
    const said = text.subline;
    const size = back ? 15 : 19;
    const width = (line: string) => measure(line, "sans", size);
    let lines = fitLines(said, columnWidth, width, back ? 2 : 3);
    let candidate = block(lines, size, bandY, 1.32, width);
    // Under the campaign's line, the subline shortens to fit the band, or gives way.
    if (back && bottomOf(candidate, bandY) > BAND_FLOOR) {
      lines = fitLines(said, columnWidth, width, 1);
      candidate = block(lines, size, bandY, 1.32, width);
    }
    if (!back || bottomOf(candidate, bandY) <= BAND_FLOOR) {
      subline = candidate;
      bandY = bottomOf(subline, bandY) + 14;
    }
  }
  let hours: Block | null = null;
  let hoursLabelY: number | null = null;
  let hoursBox: Box | null = null;
  const hoursX = boxed ? POSTER_W - POSTER_M - boxWidth + BOX_PAD : POSTER_M;
  if (groups.length) {
    hoursLabelY = Math.round(boxed ? slotTop + BOX_PAD + 10 : bandY + 12);
    const width = boxed ? boxWidth - 2 * BOX_PAD : columnWidth;
    const lines = groups.flatMap((group) => fitLines(group, width, hoursWidth, 1));
    hours = block(lines, HOURS_SIZE, hoursLabelY + 6, 1.38, hoursWidth);
    if (boxed) {
      const bottom = Math.round(bottomOf(hours, hoursLabelY) + BOX_PAD);
      hoursBox = { x: POSTER_W - POSTER_M - boxWidth, y: slotTop, width: boxWidth, height: bottom - slotTop };
    } else if (back && bottomOf(hours, hoursLabelY) > BAND_FLOOR) {
      // Under the campaign's line there may be no room left for them.
      hours = null;
      hoursLabelY = null;
    }
  }

  let proof: Block | null = null;
  if (text.proof) {
    const size = 8.6;
    const lines = fitLines(`Why the poster can say it: ${text.proof}`, INNER, (line) => measure(line, "mono", size), 2);
    proof = block(lines, size, POSTER_H - 46, 1.45, (line) => measure(line, "mono", size));
  }

  const mapTop = Math.round(y + 26);
  return {
    name,
    tagline,
    headline,
    map: { y: mapTop, height: Math.round(bandTop - 22 - mapTop) },
    bandTop,
    back,
    subline,
    hours,
    hoursLabelY,
    hoursX,
    hoursBox,
    qr: withQr ? { x: POSTER_W - POSTER_M - QR_SIZE, y: slotTop, size: QR_SIZE } : null,
    proof,
  };
}

/** A stand-in measure from character counts, for tests and for the first paint before the fonts have loaded. */
export const roughMeasure: Measure = (text, face, size, italic = false) =>
  text.length * size * (face === "mono" ? 0.6 : face === "sans" ? 0.52 : italic ? 0.43 : 0.47);

/**
 * The line over the poster's map, in capitals, for the area the survey read ("10-minute walk", "30-minute drive",
 * "25 km drive"): "EVERYONE INSIDE THE BLUE LINE IS A 10-MINUTE WALK AWAY", "… IS WITHIN A 30-MINUTE DRIVE".
 */
export function posterAreaLine(area: string): string {
  // The article follows the number as it is said: "an 8-minute walk", "an 11 km drive", "an 18-minute drive".
  const words = `${/^(8|1[18](?!\d))/.test(area) ? "AN" : "A"} ${area.toUpperCase()}`;
  return /walk$/i.test(area.trim())
    ? `EVERYONE INSIDE THE BLUE LINE IS ${words} AWAY`
    : `EVERYONE INSIDE THE BLUE LINE IS WITHIN ${words}`;
}
