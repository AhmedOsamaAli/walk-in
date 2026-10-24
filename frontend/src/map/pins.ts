/* The open category's places on the map, as labeled pins that match its lists (GapItem.tsx): its competitors inside the
   survey's area (the walk, for now) numbered 1, 2, 3… in the order the row lists them, the places only OpenStreetMap
   shows numbered after them, and the places people here love lettered A, B, C…. Pure functions: the map
   (controller.ts), the lists, the legend and the place card all read the same pins, so a number on the map is always the
   number beside the same name in the list. */
import type { FavoritePlace, GapRow, OsmPlace, PlaceCard, Travel } from "../api/types";
import { letter } from "../lib/format";
import { osmExtra } from "../lib/gap";

/** How many competitors and how many favorites the open row lists, and so how many the map labels. */
export const LISTED = 6;
/** How many of the places only OpenStreetMap shows inside the area get a number after Qloo's. */
export const OSM_PINNED = 6;
/**
 * Farthest a loved place outside the area may be from the site and still be drawn: favorites are searched within 15 km
 * of it, so anything far beyond is bad data. Places inside the area are drawn wherever it reaches.
 */
export const MAX_PLACE_M = 60_000;
/** The survey's area as it reads inside a sentence. Surveys measure a walk today; a drive or a road distance will
 * pass their own words to the functions below that take an `area`. */
export const AREA = "the walk";

/** The area inside a sentence for how the survey measured it: a drive, by time or by road distance, or a walk. */
export function areaWord(travel: Travel | null | undefined): string {
  return travel === "drive" || travel === "distance" ? "the drive" : AREA;
}

/**
 * - inside: a competitor Qloo lists inside the area;
 * - osm: a place of the kind only OpenStreetMap shows inside the area;
 * - loved: a place people here love more than the rest of the city does;
 * - famous: one of the city's famous spots, shown when too few places stand out as loved here.
 */
export type PinRole = "inside" | "osm" | "loved" | "famous";

export interface Pin {
  /** Unique across categories: the category, the list and the place's position in it. */
  key: string;
  /** "1", "2"… for the places inside the area, "A", "B"… for the loved ones. */
  mark: string;
  role: PinRole;
  name: string;
  lat: number;
  lon: number;
  /** From the site, in meters. */
  distanceM: number | null;
  /** Inside the survey's area (the walk, for now). */
  inArea: boolean;
  /** Qloo's card for the place; null for a place only OpenStreetMap shows. */
  place: PlaceCard | null;
  osm: OsmPlace | null;
  /** A competitor that is also one of the places people here love: one pin, one number, in both lists. */
  alsoLoved: boolean;
}

/** A list item's pin, by the item's position in its list; null when the place has no location to draw. */
export interface ListMark {
  key: string;
  mark: string;
  role: PinRole;
}

export interface PinSummary {
  genre: string;
  kind: "local" | "citywide";
  /** Competitors drawn, and how many Qloo lists inside the area in all. */
  inside: number;
  insideTotal: number;
  insideCapped: boolean;
  osm: number;
  /** Loved or famous places drawn outside the area, and the median trip to them. */
  outside: number;
  outsideMedianKm: number | null;
  /** Loved or famous places drawn inside the area that are not among its numbered competitors. */
  lovedInside: number;
}

export interface GapPins {
  /** In drawing and tabbing order: 1, 2, 3…, then A, B, C…. */
  pins: Pin[];
  competitors: (ListMark | null)[];
  favorites: (ListMark | null)[];
  osm: (ListMark | null)[];
  summary: PinSummary;
}

type Located<T> = T & { lat: number; lon: number };

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

/** A place with a location the map can draw. */
export function located<T extends { lat?: number | null; lon?: number | null }>(place: T): place is Located<T> {
  return finite(place.lat) && finite(place.lon);
}

/**
 * A loved place the map can draw: located, and inside the area or not far beyond where favorites are searched. The
 * places inside the area are drawn wherever it reaches, so a drive or a road distance keeps its far competitors.
 */
export function pinnable(place: FavoritePlace): place is Located<FavoritePlace> {
  return located(place) && (place.within_walk === true || place.distance_m == null || place.distance_m <= MAX_PLACE_M);
}

const normalized = (name: string | null | undefined) => (name ?? "").trim().toLowerCase().replace(/\s+/g, " ");

/** Meters between two nearby points, flat-earth: enough to tell one storefront from the next. */
function nearM(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const dLat = (a.lat - b.lat) * 111_320;
  const dLon = (a.lon - b.lon) * 111_320 * Math.cos((a.lat * Math.PI) / 180);
  return Math.hypot(dLat, dLon);
}

/** The same place in two lists: the same Qloo id, or, without ids, the same name within 80 m. */
export function samePlace(a: PlaceCard, b: PlaceCard): boolean {
  if (a.id && b.id) return a.id === b.id;
  if (!normalized(a.name) || normalized(a.name) !== normalized(b.name)) return false;
  return !located(a) || !located(b) || nearM(a, b) <= 80;
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((x, y) => x - y);
  const mid = Math.floor(sorted.length / 2);
  const upper = sorted[mid] ?? 0;
  return sorted.length % 2 ? upper : ((sorted[mid - 1] ?? upper) + upper) / 2;
}

/** The open category's pins, and each list item's mark. */
export function gapPins(gap: GapRow): GapPins {
  const prefix = gap.genre_id;
  const pins: Pin[] = [];
  const pin = (fields: Omit<Pin, "alsoLoved">): Pin => {
    const made = { ...fields, alsoLoved: false };
    pins.push(made);
    return made;
  };
  const markOf = (made: Pin): ListMark => ({ key: made.key, mark: made.mark, role: made.role });

  let number = 0;
  const competitors = (gap.competitors ?? []).slice(0, LISTED).map((place, k): ListMark | null => {
    if (!located(place)) return null;
    number += 1;
    return markOf(
      pin({
        key: `${prefix}#c${k}`,
        mark: String(number),
        role: "inside",
        name: place.name ?? "Unnamed place",
        lat: place.lat,
        lon: place.lon,
        distanceM: place.distance_m ?? null,
        inArea: true,
        place,
        osm: null,
      }),
    );
  });

  const extra = osmExtra(gap);
  const osm = extra.map((place, k): ListMark | null => {
    if (k >= OSM_PINNED || !located(place)) return null;
    number += 1;
    return markOf(
      pin({
        key: `${prefix}#o${k}`,
        mark: String(number),
        role: "osm",
        name: place.name,
        lat: place.lat,
        lon: place.lon,
        distanceM: place.distance_m ?? null,
        inArea: true,
        place: null,
        osm: place,
      }),
    );
  });

  const role: PinRole = gap.favorites_kind === "local" ? "loved" : "famous";
  let letters = 0;
  const favorites = (gap.favorites ?? []).slice(0, LISTED).map((place: FavoritePlace, k): ListMark | null => {
    // A favorite that is also a numbered competitor keeps the competitor's number: one place, one pin.
    const twin = pins.find((made) => made.role === "inside" && made.place !== null && samePlace(made.place, place));
    if (twin) {
      twin.alsoLoved = true;
      return markOf(twin);
    }
    if (!pinnable(place)) return null;
    const made = pin({
      key: `${prefix}#f${k}`,
      mark: letter(letters),
      role,
      name: place.name ?? "Unnamed place",
      lat: place.lat,
      lon: place.lon,
      distanceM: place.distance_m ?? null,
      inArea: place.within_walk === true,
      place,
      osm: null,
    });
    letters += 1;
    return markOf(made);
  });

  const away = pins.filter((made) => (made.role === "loved" || made.role === "famous") && !made.inArea);
  const trips = away.map((made) => made.distanceM).filter(finite);
  const middle = median(trips);
  return {
    pins,
    competitors,
    favorites,
    osm,
    summary: {
      genre: gap.genre,
      kind: gap.favorites_kind,
      inside: pins.filter((made) => made.role === "inside").length,
      insideTotal: gap.nearby_count,
      insideCapped: gap.nearby_capped,
      osm: pins.filter((made) => made.role === "osm").length,
      outside: away.length,
      outsideMedianKm: middle === null ? null : Math.round(middle / 100) / 10,
      lovedInside: pins.filter((made) => (made.role === "loved" || made.role === "famous") && made.inArea).length,
    },
  };
}

/* ---------- Words: a category as it reads inside a sentence (app/survey/evidence.py) ---------- */

// Words that keep their capital inside a sentence: nationalities and cuisines ("Mexican", "Middle Eastern").
const NATIONAL = /^[A-Z][a-z]+(an|ese|ish|ic|ian|ern)$/;
const NOT_NATIONAL = new Set(["Vegan", "Organic", "Classic", "Music", "Public", "Electric", "Ethnic", "Exotic", "Comic"]);
const PROPER_WORDS = new Set(["Greek", "Thai", "French", "Dutch", "Basque", "Creole", "Cajun", "Swiss", "Czech", "Kosher", "Halal"]);
const QUALIFIERS = new Set(["New", "Latin", "Middle", "South", "North", "East", "West", "Central", "Southern", "Northern"]);
// The last word of a category that names the place itself, and its plural ("coffee shop" -> "coffee shops").
const PLACE_PLURALS: Readonly<Record<string, string>> = {
  shop: "shops", bar: "bars", venue: "venues", house: "houses", bakery: "bakeries", brewery: "breweries", club: "clubs",
  cafe: "cafes", café: "cafés", restaurant: "restaurants", pub: "pubs", hall: "halls", studio: "studios",
  gallery: "galleries", salon: "salons", spa: "spas", gym: "gyms", store: "stores", kitchen: "kitchens",
  lounge: "lounges", diner: "diners", deli: "delis", bistro: "bistros", pizzeria: "pizzerias", taproom: "taprooms",
  boutique: "boutiques", market: "markets", parlor: "parlors", parlour: "parlours", eatery: "eateries",
  bookstore: "bookstores", theater: "theaters", theatre: "theatres", cafeteria: "cafeterias",
  steakhouse: "steakhouses", roastery: "roasteries", barbershop: "barbershops",
};

const proper = (word: string) =>
  (NATIONAL.test(word) && !NOT_NATIONAL.has(word)) || PROPER_WORDS.has(word) || (word.includes("-") && /^[A-Z]/.test(word));
const shouting = (word: string) => /[A-Z]/.test(word) && word === word.toUpperCase();

/** "Wine Bar" -> "wine bar"; "Mexican" and "New American" keep their capitals. */
export function inSentence(genre: string): string {
  const words = genre.trim().replace(/\s+restaurant$/i, "").split(/\s+/);
  return words
    .map((word, index) => {
      const next = words[index + 1];
      const qualifies = QUALIFIERS.has(word) && next !== undefined && proper(next);
      return proper(word) || qualifies || shouting(word) ? word : word.toLowerCase();
    })
    .join(" ");
}

/** The plural of the last word when it names the place ("bakeries"), or null ("seafood"). */
function placePlural(phrase: string): string | null {
  const last = phrase.split(" ").at(-1)?.toLowerCase() ?? "";
  return /[+&]/.test(phrase) ? null : (PLACE_PLURALS[last] ?? null);
}

/** "Coffee shop" -> "coffee shops", "Seafood" -> "seafood places". */
export function plural(genre: string): string {
  const phrase = inSentence(genre);
  const last = placePlural(phrase);
  return last ? [...phrase.split(" ").slice(0, -1), last].join(" ") : `${phrase} places`;
}

/** "Coffee shop" -> "coffee shop", "Seafood" -> "seafood place". */
export function singular(genre: string): string {
  const phrase = inSentence(genre);
  return placePlural(phrase) ? phrase : `${phrase} place`;
}

/** "1 coffee shop", "7 coffee shops", "50+ coffee shops". */
export function countOf(genre: string, count: number, capped = false): string {
  return `${count}${capped ? "+" : ""} ${count === 1 && !capped ? singular(genre) : plural(genre)}`;
}

/* ---------- The legend's lines, and the words a pin is announced with ---------- */

/** "Inside the walk: 5 seafood places", or "Inside the walk: 6 of 12 brunch places" when the list shows fewer. */
export function insideLine(summary: PinSummary, area = AREA): string {
  const total = Math.max(summary.insideTotal, summary.inside);
  if (total > summary.inside || summary.insideCapped) {
    return `Inside ${area}: ${summary.inside} of ${countOf(summary.genre, total, summary.insideCapped)}`;
  }
  return `Inside ${area}: ${countOf(summary.genre, summary.inside)}`;
}

export function osmLine(summary: PinSummary): string {
  return `Only on OpenStreetMap: ${summary.osm}`;
}

/** "Loved, outside the walk: 5 · median 3.3 km", or the city's famous spots when too few stand out as loved here. */
export function outsideLine(summary: PinSummary, area = AREA): string {
  const lead = summary.kind === "local" ? `Loved, outside ${area}` : "City's famous spots";
  const trip = summary.outsideMedianKm === null ? "" : ` · median ${summary.outsideMedianKm.toFixed(1)} km`;
  return `${lead}: ${summary.outside}${trip}`;
}

export function lovedInsideLine(summary: PinSummary, area = AREA): string {
  return `${summary.kind === "local" ? "Loved" : "City's famous spots"}, inside ${area}: ${summary.lovedInside}`;
}

/** "3.3 km away", "650 m away". */
export function awayText(meters: number | null): string {
  if (meters === null) return "";
  return meters < 950 ? `${Math.round(meters / 10) * 10} m away` : `${(meters / 1000).toFixed(1)} km away`;
}

function roleParts(pin: Pin, area: string): string[] {
  const where = pin.inArea ? `inside ${area}` : awayText(pin.distanceM);
  switch (pin.role) {
    case "inside":
      return [`inside ${area}`, pin.alsoLoved ? "loved by people here" : ""];
    case "osm":
      return [`inside ${area}`, "only on OpenStreetMap"];
    case "loved":
      return ["loved by people here", where];
    case "famous":
      return ["one of the city's famous spots", where];
  }
}

/** What the pin is, in a few words: "Inside the walk", "Loved by people here · 3.3 km away". */
export function roleText(pin: Pin, area = AREA): string {
  const text = roleParts(pin, area).filter(Boolean).join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The pin's name for screen readers: "1, Harbor Fish: inside the walk". */
export function pinLabel(pin: Pin, area = AREA): string {
  return `${pin.mark}, ${pin.name}: ${roleParts(pin, area).filter(Boolean).join(", ")}`;
}

/* ---------- Keeping labels legible: no badge over another, or over the site ---------- */

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

/** Rings of spots tried around a crowded badge, and the gap kept between badges, in pixels. */
const RINGS = 4;
const GAP = 3;

const overlaps = (a: Box, b: Box) =>
  a.left < b.right + GAP && b.left < a.right + GAP && a.top < b.bottom + GAP && b.top < a.bottom + GAP;
const contains = (outer: Box, inner: Box) =>
  inner.left >= outer.left && inner.top >= outer.top && inner.right <= outer.right && inner.bottom <= outer.bottom;

/**
 * Where each badge sits relative to its place, so none covers another badge or anything in `keepClear` (the site and
 * its tag, the map's controls): badges that fit stay on their place; a crowded one moves out to the nearest free spot,
 * away from `from` (the site) first, and the map draws a short line back to the place. A badge whose place is inside
 * `view` stays wholly inside it. Badges earlier in the list are placed first.
 */
export function declutter(
  points: readonly Point[],
  size: number,
  keepClear: readonly Box[],
  from: Point | null,
  view: Box | null = null,
): Point[] {
  const half = size / 2;
  const taken: Box[] = [...keepClear];
  const boxAt = (point: Point, offset: Point): Box => ({
    left: point.x + offset.x - half,
    top: point.y + offset.y - half,
    right: point.x + offset.x + half,
    bottom: point.y + offset.y + half,
  });
  return points.map((point) => {
    const ahead = from && (point.x !== from.x || point.y !== from.y) ? Math.atan2(point.y - from.y, point.x - from.x) : -Math.PI / 2;
    // The view a badge must stay inside: only for a place in view.
    const within = view && point.x >= view.left && point.x <= view.right && point.y >= view.top && point.y <= view.bottom ? view : null;
    let chosen: Point = { x: 0, y: 0 };
    search: for (let ring = 0; ring <= RINGS; ring += 1) {
      const tries = ring === 0 ? 1 : 12;
      for (let k = 0; k < tries; k += 1) {
        // Straight away from the site first, then 30° either side of it, then 60°, and so on round.
        const turn = Math.ceil(k / 2) * (k % 2 ? 1 : -1) * (Math.PI / 6);
        const reach = ring * (size + GAP);
        // `|| 0` turns -0 into 0.
        const offset = { x: Math.round(reach * Math.cos(ahead + turn)) || 0, y: Math.round(reach * Math.sin(ahead + turn)) || 0 };
        const box = boxAt(point, offset);
        if (within && !contains(within, box)) continue;
        if (!taken.some((other) => overlaps(other, box))) {
          chosen = offset;
          break search;
        }
      }
    }
    taken.push(boxAt(point, chosen));
    return chosen;
  });
}
