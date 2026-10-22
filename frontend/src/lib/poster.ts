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

export interface PosterLayout {
  name: Block;
  tagline: Block | null;
  headline: Block | null;
  map: { y: number; height: number };
  bandTop: number;
  subline: Block | null;
  hours: Block | null;
  hoursLabelY: number | null;
  qr: { x: number; y: number; size: number };
  proof: Block | null;
}

export interface PosterText {
  name: string;
  tagline: string | null;
  headline: string | null;
  subline: string | null;
  hours: string | null;
  proof: string | null;
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

/** Lays the poster out; when the walk's map would be too small, the name is set smaller until it fits. */
export function layoutPoster(text: PosterText, measure: Measure): PosterLayout {
  let layout = attempt(text, measure, 1);
  for (const scale of [0.86, 0.74, 0.62]) {
    if (layout.map.height >= 170) break;
    layout = attempt(text, measure, scale);
  }
  return layout;
}

function attempt(text: PosterText, measure: Measure, scale: number): PosterLayout {
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
  const qrSize = 148;
  const columnWidth = INNER - qrSize - 28;
  let subline: Block | null = null;
  let bandY = bandTop + 26;
  if (text.subline) {
    const size = 19;
    const lines = fitLines(text.subline, columnWidth, (line) => measure(line, "sans", size), 3);
    subline = block(lines, size, bandY, 1.32, (line) => measure(line, "sans", size));
    bandY = bottomOf(subline, bandY) + 14;
  }
  let hours: Block | null = null;
  let hoursLabelY: number | null = null;
  if (text.hours) {
    hoursLabelY = Math.round(bandY + 12);
    const size = 13.5;
    const groups = text.hours.split(" · ").filter(Boolean).slice(0, 4);
    const lines = groups.flatMap((group) => fitLines(group, columnWidth, (line) => measure(line, "sans", size), 1));
    hours = block(lines, size, hoursLabelY + 6, 1.38, (line) => measure(line, "sans", size));
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
    subline,
    hours,
    hoursLabelY,
    qr: { x: POSTER_W - POSTER_M - qrSize, y: bandTop + 24, size: qrSize },
    proof,
  };
}

/** A stand-in measure from character counts, for tests and for the first paint before the fonts have loaded. */
export const roughMeasure: Measure = (text, face, size, italic = false) =>
  text.length * size * (face === "mono" ? 0.6 : face === "sans" ? 0.52 : italic ? 0.43 : 0.47);
