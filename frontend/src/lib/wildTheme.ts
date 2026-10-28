/* A themed wild card (Poster.tsx, WildTheme.tsx, DesignContent.tsx): a kind of place people here love, built around a
   theme from what they watch, hear and follow. The server builds the theme; a recorded survey can come from another
   version of it, so its parts are read with care. Pure, so they are tested without a browser. */
import type { Concept, ConceptTheme, ThemeCard, ThemeDomain, ThemeDraws } from "../api/types";
import { list, naturalList } from "./format";

/** What each kind of title is called on its card. */
export const DOMAIN_LABELS: Record<ThemeDomain, string> = {
  tv: "TV",
  movies: "Film",
  podcasts: "Podcast",
  artists: "Artist",
  brands: "Brand",
};

/** A poster shows this many of the titles its theme is built on; the design sheet shows them all. */
export const POSTER_TITLES = 4;

/** Said after who the titles draw when the server gives no basis of its own. */
export const DRAWS_BASIS = "Qloo audience leans, not head counts.";

const text = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

const isDomain = (value: unknown): value is ThemeDomain => typeof value === "string" && Object.hasOwn(DOMAIN_LABELS, value);

function isCard(value: unknown): value is ThemeCard {
  if (typeof value !== "object" || value === null) return false;
  const card = value as Partial<Record<keyof ThemeCard, unknown>>;
  return isDomain(card.domain) && text(card.name) !== "";
}

const GENDERS: Readonly<Record<string, string>> = { female: "female", women: "female", male: "male", men: "male" };

/** "female" or "male", however the server words it; null for no clear lean. */
export function genderWord(gender: unknown): string | null {
  return typeof gender === "string" ? (GENDERS[gender.trim().toLowerCase()] ?? null) : null;
}

function drawsOf(value: unknown): ThemeDraws | null {
  if (typeof value !== "object" || value === null) return null;
  const draws = value as Partial<Record<keyof ThemeDraws, unknown>>;
  const ages = list(draws.ages).map((band) => band.trim());
  const gender = genderWord(draws.gender);
  return ages.length || gender ? { ages, gender, basis: text(draws.basis) } : null;
}

/** The concept's theme when it has one (a label at least), its lists cleaned; null for a concept without one. */
export function themeOf(concept: Concept): ConceptTheme | null {
  if (typeof concept.theme !== "object" || concept.theme === null) return null;
  const theme = concept.theme as Partial<Record<keyof ConceptTheme, unknown>>;
  const label = text(theme.label);
  if (!label) return null;
  const cards: unknown[] = Array.isArray(theme.built_on) ? theme.built_on : [];
  return {
    key: text(theme.key),
    label,
    program: list(theme.program).map((line) => line.trim()),
    built_on: cards.filter(isCard),
    draws: drawsOf(theme.draws),
    basis: text(theme.basis),
  };
}

/** The youngest and oldest age of a span; null at an open end ("Under 25" has no youngest, "55+" no oldest). */
type Span = [from: number | null, to: number | null];

/** The ages one of Qloo's bands covers, as the server names them ("Under 25", "25–29", "55+"); null for another name. */
function bandSpan(band: string): Span | null {
  const under = /^under (\d+)$/i.exec(band);
  if (under) return [null, Number(under[1]) - 1];
  const span = /^(\d+)\s*[–-]\s*(\d+)$/.exec(band);
  if (span) return [Number(span[1]), Number(span[2])];
  const over = /^(\d+)\+$/.exec(band);
  return over ? [Number(over[1]), null] : null;
}

const spanText = ([from, to]: Span): string =>
  from === null ? `Under ${(to ?? 0) + 1}` : to === null ? `${from}+` : `${from}–${to}`;

/**
 * Age bands as a reader takes them: bands that run on make one span ("25–29" and "30–34" read "25–34"), bands apart
 * stay apart ("25–29 and 45–54"); names that are not Qloo's bands are said as they come.
 */
export function agesText(bands: readonly string[]): string {
  const spans: Span[] = [];
  for (const band of bands) {
    const span = bandSpan(band.trim());
    if (!span) return naturalList([...new Set(bands.map((name) => name.trim()).filter(Boolean))]);
    spans.push(span);
  }
  spans.sort((a, b) => (a[0] ?? -1) - (b[0] ?? -1));
  const runs: Span[] = [];
  for (const [from, to] of spans) {
    const run = runs.at(-1);
    // A band that starts inside the last run, or right after it, lengthens that run.
    if (run?.[1] != null && from !== null && from <= run[1] + 1) run[1] = to === null ? null : Math.max(run[1], to);
    else runs.push([from, to]);
  }
  return naturalList(runs.map(spanText));
}

/** Who the theme's titles draw, worded like the audience section: "Ages 25–34 most · leans toward women"; null when Qloo
 * showed no clear lean. */
export function drawsText(draws: ThemeDraws): string | null {
  const gender = genderWord(draws.gender);
  const ages = draws.ages.length ? agesText(draws.ages) : "";
  const parts = [
    ages ? `ages ${ages.charAt(0).toLowerCase()}${ages.slice(1)} most` : null,
    gender ? `leans toward ${gender === "female" ? "women" : "men"}` : null,
  ];
  const line = parts.filter((part) => part !== null).join(" · ");
  return line ? line.charAt(0).toUpperCase() + line.slice(1) : null;
}
