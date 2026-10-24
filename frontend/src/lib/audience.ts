/* Who the places people here love draw (Contract 10-23), and a chain's own stores in the area: the ad setting the
   audience implies, each age band's lean in words, and the chain's count as the verdict shows it. Pure, so they are
   tested without a browser. */
import type { Audience, ChainCheck } from "../api/types";

/** A lean at least this far from 0 reads as more, or fewer, than everyone; nearer, as about like everyone. The server's
 * audience.py names an age group from the same 0.1. */
export const CLEAR_LEAN = 0.1;

export type LeanWord = "more" | "fewer" | "even";

export function leanWord(lean: number): LeanWord {
  return lean >= CLEAR_LEAN ? "more" : lean <= -CLEAR_LEAN ? "fewer" : "even";
}

const LEAN_WORDS: Record<LeanWord, string> = {
  more: "more than everyone",
  fewer: "fewer than everyone",
  even: "about like everyone",
};

/** The six bands in words, for a screen reader: "Under 25: fewer than everyone; …; 35–44: more than everyone". */
export function bandsText(audience: Pick<Audience, "bands">): string {
  return audience.bands.map(({ band, lean }) => `${band}: ${LEAN_WORDS[leanWord(lean)]}`).join("; ");
}

/** Where a band's bar sits on its track, in percent: it starts at the middle (like everyone) and runs right for more,
 * left for fewer, up to the track's end at a lean of 1. */
export function barSpan(lean: number): { left: number; width: number } {
  const clamped = Math.max(-1, Math.min(1, Number.isFinite(lean) ? lean : 0));
  const width = Math.round(Math.abs(clamped) * 500) / 10;
  return { left: clamped >= 0 ? 50 : 50 - width, width };
}

/**
 * The bands the audience's age group covers, as the server reads it: the band leaning most, widened to the neighbours
 * that lean clearly too. None when the server names no age group.
 */
export function namedBands(audience: Pick<Audience, "ages" | "bands">): Set<string> {
  const { bands } = audience;
  if (!audience.ages || !bands.length) return new Set();
  const top = bands.reduce((best, band, index) => (band.lean > (bands[best]?.lean ?? -Infinity) ? index : best), 0);
  if ((bands[top]?.lean ?? 0) < CLEAR_LEAN) return new Set();
  let first = top;
  let last = top;
  while (first > 0 && (bands[first - 1]?.lean ?? 0) >= CLEAR_LEAN) first -= 1;
  while (last < bands.length - 1 && (bands[last + 1]?.lean ?? 0) >= CLEAR_LEAN) last += 1;
  return new Set(bands.slice(first, last + 1).map((band) => band.band));
}

/** The age and gender an ad platform takes: the server's own words when it sent them ("Ages 35–44, women"), else read
 * from the leans; null when it would say nothing. */
export function adText(audience: Audience): string | null {
  if (audience.ad !== undefined) return audience.ad;
  const setting = adSetting(audience);
  return setting ? setting.charAt(0).toUpperCase() + setting.slice(1) : null;
}

/** "ages 35–44, women and men": what an ad platform's audience takes; null when it would say nothing. */
export function adSetting(audience: Audience): string | null {
  const { age_min: min, age_max: max, gender } = audience;
  const ages =
    min != null && max != null ? `ages ${min}–${max}` : min != null ? `ages ${min}+` : max != null ? `ages ${max} and under` : null;
  if (!ages && !gender) return null;
  return `${ages ?? "all ages"}, ${gender ?? "women and men"}`;
}

/** The server's line, with a count that hit the limit said as "50+" even if the line gives the bare number. */
export function chainLine(chain: ChainCheck): string {
  const { line, inside, capped } = chain;
  if (!capped || line.includes(`${inside}+`)) return line;
  return line.replace(new RegExp(`(^|\\D)${inside}(?=\\s)`), `$1${inside}+`);
}

/** The sheet's title for the audience: the people to win here, or, when it is the category's everywhere, said so. */
export const audienceTitle = (audience: Audience): string =>
  audience.general ? "Who this kind of place draws" : "Who you'd win";

/** Names as a list says them, a name that comes up more than once (a chain's branches) said once with its count:
 * "Costa Coffee (3 places)". In the order they first come. */
export function namesOnce(names: string[]): string[] {
  const counts = new Map<string, number>();
  for (const name of names) counts.set(name, (counts.get(name) ?? 0) + 1);
  return [...counts].map(([name, count]) => (count > 1 ? `${name} (${count} places)` : name));
}

/** The age bands of the places of this kind already inside the area, when the server read them (Contract 10-23b). */
export type InsideAudience = NonNullable<Audience["inside"]>;

/** The two rows of the comparison, in the loved places' band order: who you'd win, over who the area's places draw now.
 * A band the inside row lacks reads as like everyone. */
export function compareRows(audience: Audience, inside: InsideAudience, area: string): {
  key: "loved" | "inside";
  name: string;
  named: Set<string>;
  bands: { band: string; lean: number }[];
}[] {
  const leans = new Map(inside.bands.map(({ band, lean }) => [band, lean]));
  const insideBands = audience.bands.map(({ band }) => ({ band, lean: leans.get(band) ?? 0 }));
  return [
    { key: "loved", name: "The places people here love", named: namedBands(audience), bands: audience.bands },
    { key: "inside", name: `Already inside the ${area}`, named: namedBands({ ages: inside.ages, bands: insideBands }), bands: insideBands },
  ];
}

/** The launch plan's line beside the channels: the audience's own line, or, when the sheet shows it above, what the
 * channels' ages and gender follow. */
export function peopleNote(people: Audience, above: boolean): string {
  if (!above) return people.line;
  const who = people.general ? "this kind of place draws in general" : "the loved places draw";
  return adText(people) !== null
    ? `The ages and gender in these settings follow who ${who}, shown above.`
    : `No age or gender stands out in who ${who}, so these settings leave both open.`;
}
