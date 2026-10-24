import type { Ages, Focus, Intent, Kitchen, PlaceCard, PlaceHit, RunRequest, RunSite, Travel, Walk } from "../api/types";
import {
  areaOf,
  areaShort,
  KM_MAX,
  KM_MIN,
  KM_PICKS,
  km2Text,
  MINUTE_PICKS,
  MINUTES_MAX,
  MINUTES_MIN,
  parseKm,
  parseMinutes,
  walkShort,
  type Area,
} from "../lib/area";
import { FOCUS_LABELS, floorArea, isFocus, isIntent, isKitchen, KITCHEN_LABELS } from "../lib/format";
import type { Site } from "./site";

export type AreaUnit = "m2" | "ft2";
export type Choice = "yes" | "no" | "unsure";

/** Everything the owner sets in the brief before a survey. */
export interface BriefForm {
  intent: Intent;
  /** How far customers come from: a walk or a drive of `minutes`, or a road distance of `km`. */
  travel: Travel;
  /** The quick pick for the walk or the drive: 5, 10, 15, 30 or 60 minutes. */
  minutes: number;
  /** The quick pick for the road distance: 5, 10, 25, 50 or 100 km. */
  km: number;
  /** What is typed in "Other", for the walk or the drive and for the distance: while it holds text, it wins over the pick. */
  otherMinutes: string;
  otherKm: string;
  /** Who the owner wants to serve: everyone, or an age group whose loves decide what counts as missing. */
  ages: Ages;
  focus: Focus;
  notes: string;
  /** The business to open, as the owner words it. */
  business: string;
  /** The owner's place on Qloo, when improving it. */
  place: PlaceHit | null;
  area: string;
  areaUnit: AreaUnit;
  kitchen: Kitchen | "unsure";
  outdoor: Choice;
}

export const initialBrief: BriefForm = {
  intent: "explore",
  travel: "walk",
  minutes: 10,
  km: 10,
  otherMinutes: "",
  otherKm: "",
  ages: "all",
  focus: "any",
  notes: "",
  business: "",
  place: null,
  area: "",
  areaUnit: "m2",
  kitchen: "unsure",
  outdoor: "unsure",
};

export const BUSINESS_MAX = 80;

/** The age groups the brief offers, in order, as the chips and the run header name them. */
export const AGES_LABELS: Record<Ages, string> = {
  all: "Everyone",
  under_25: "Under 25",
  "25_34": "25–34",
  "35_54": "35–54",
  "55_plus": "55+",
};
export const isAges = (value: unknown): value is Ages => typeof value === "string" && Object.hasOwn(AGES_LABELS, value);

/** The age focus as the run header says it, "For 25–34"; null for everyone. */
export const agesLine = (ages: unknown): string | null => (isAges(ages) && ages !== "all" ? `For ${AGES_LABELS[ages]}` : null);

const AREA_LIMITS: Record<Travel, string> = {
  walk: `A walk must be between ${MINUTES_MIN} and ${MINUTES_MAX} minutes.`,
  drive: `A drive must be between ${MINUTES_MIN} and ${MINUTES_MAX} minutes.`,
  distance: `The distance must be between ${KM_MIN} and ${KM_MAX} km.`,
};

/** The number typed in "Other": within the limits, null for one out of them, undefined while nothing is typed. */
function typed(form: BriefForm): number | null | undefined {
  const text = form.travel === "distance" ? form.otherKm : form.otherMinutes;
  if (!text.trim()) return undefined;
  return form.travel === "distance" ? parseKm(text) : parseMinutes(text);
}

/**
 * The area the brief asks for, to trace and to survey: what "Other" says, over the quick pick; null while "Other" holds
 * a number out of the limits.
 */
export function briefArea(form: BriefForm): Area | null {
  const other = typed(form);
  if (other === null) return null;
  return form.travel === "distance"
    ? { travel: "distance", km: other ?? form.km }
    : { travel: form.travel, minutes: other ?? form.minutes };
}

/** The area as far as the brief can tell: the quick pick stands in for a number out of the limits. */
export function formArea(form: BriefForm): Area {
  const pick: Area = form.travel === "distance" ? { travel: "distance", km: form.km } : { travel: form.travel, minutes: form.minutes };
  return briefArea(form) ?? pick;
}

/** Why the number typed in "Other" cannot be used; null when it can, or when nothing is typed. */
export const areaProblem = (form: BriefForm): string | null => (typed(form) === null ? AREA_LIMITS[form.travel] : null);

/** What still stops the survey from starting, as the button's hint; null when it can start. */
export function missing(site: Site | null, form: BriefForm): string | null {
  if (!site) return "Choose a site first.";
  if (form.intent === "open" && !form.business.trim()) return "Say what you want to open.";
  if (form.intent === "improve" && !form.place) return "Find your place on Qloo first.";
  const area = areaProblem(form);
  if (area) return area;
  if (form.intent !== "improve" && form.area.trim() && floorArea(form.area, form.areaUnit) === null) {
    return "The floor area must be between 10 and 2,000 m² (110–21,500 ft²).";
  }
  return null;
}

/**
 * Whether the unit's food prep matters, so the brief asks for it and the run sends it: when food can be involved, that
 * is any business or food and drink while finding what is missing, and always for an idea under test (it matters only
 * if the idea serves food). Not for shops or leisure, nor when improving a place, whose unit is not asked. The answer
 * stays in the form while the question is hidden, so switching back brings it back.
 */
export function foodPrepAsked(form: BriefForm): boolean {
  if (form.intent === "open") return true;
  return form.intent === "explore" && (form.focus === "any" || form.focus === "food_drink");
}

/** The survey the brief asks for. Improving a place compares the place itself, so unit details and notes stay out. */
export function runRequest(site: Site, form: BriefForm): RunRequest {
  const area = formArea(form);
  const run: RunRequest = {
    lat: site.lat,
    lon: site.lon,
    label: site.label,
    focus: form.intent === "explore" ? form.focus : "any",
    notes: form.intent === "improve" ? "" : form.notes.trim(),
    minutes: area.travel === "distance" ? form.minutes : area.minutes,
    intent: form.intent,
    travel: area.travel,
  };
  if (area.travel === "distance") run.km = area.km;
  if (form.ages !== "all") run.ages = form.ages;
  if (form.intent === "open") run.business = form.business.trim().slice(0, BUSINESS_MAX);
  if (form.intent === "improve" && form.place) run.placeId = form.place.id;
  if (form.intent !== "improve") {
    const size = floorArea(form.area, form.areaUnit);
    if (size !== null) run.sizeM2 = size;
    if (form.kitchen !== "unsure" && foodPrepAsked(form)) run.kitchen = form.kitchen;
    if (form.outdoor !== "unsure") run.outdoor = form.outdoor === "yes";
  }
  return run;
}

/** The unit as the title block states it: "60 m² · Light prep, no hood · No outdoor space"; null when not described. */
export function unitLine(run: RunRequest): string | null {
  const parts: string[] = [];
  if (run.sizeM2 !== undefined) parts.push(`${run.sizeM2.toLocaleString("en-US")} m²`);
  if (run.kitchen) parts.push(KITCHEN_LABELS[run.kitchen]);
  if (run.outdoor !== undefined) parts.push(run.outdoor ? "Outdoor space" : "No outdoor space");
  return parts.length ? parts.join(" · ") : null;
}

/**
 * The title block's catchment: the area in the server's words once it is traced (else as the brief asked for it), its
 * size, and the age focus: "30-min drive", "272 km²", "For 25–34".
 */
export function catchmentLines(run: RunRequest, walk: Walk | null): string[] {
  const lines = [walk ? walkShort(walk) : areaShort(areaOf(run))];
  if (walk) lines.push(`${km2Text(walk.area_km2)} km²`);
  const ages = agesLine(run.ages);
  if (ages) lines.push(ages);
  return lines;
}

/** What the survey is about, for the title block's second field. */
export function askedLine(run: RunRequest, place: PlaceHit | null): { label: string; line: string } {
  if (run.intent === "open") return { label: "Your idea", line: run.business ?? "" };
  if (run.intent === "improve") {
    const genre = place?.genres?.[0];
    return { label: "Your place", line: [place?.name ?? run.label, genre].filter(Boolean).join(" · ") };
  }
  return { label: "Business", line: FOCUS_LABELS[run.focus] };
}

/**
 * The site and brief a recorded survey was run with, as the server read them: its title block is rebuilt from them, and
 * a new survey can start from them. `place` is the owner's place the run found, when improving it. A survey made before
 * drives and distances is a walk, for everyone; a time or a distance off the quick picks comes back in "Other".
 */
export function briefOf(site: RunSite, place: PlaceCard | null): { site: Site; form: BriefForm } {
  const intent = isIntent(site.intent) ? site.intent : "explore";
  const placeId = intent === "improve" && typeof site.place_id === "string" ? site.place_id : "";
  const size = typeof site.size_m2 === "number" && Number.isFinite(site.size_m2) ? site.size_m2 : null;
  const area = areaOf(site);
  const minutes = area.travel === "distance" ? null : area.minutes;
  const km = area.travel === "distance" ? area.km : null;
  const form: BriefForm = {
    ...initialBrief,
    intent,
    travel: area.travel,
    minutes: minutes !== null && MINUTE_PICKS.includes(minutes) ? minutes : initialBrief.minutes,
    km: km !== null && KM_PICKS.includes(km) ? km : initialBrief.km,
    otherMinutes: minutes !== null && !MINUTE_PICKS.includes(minutes) ? String(minutes) : "",
    otherKm: km !== null && !KM_PICKS.includes(km) ? String(km) : "",
    ages: isAges(site.ages) ? site.ages : "all",
    focus: isFocus(site.focus) ? site.focus : "any",
    notes: typeof site.notes === "string" ? site.notes : "",
    business: typeof site.business === "string" ? site.business : "",
    place: placeId
      ? {
          id: placeId,
          name: place?.name ?? site.label,
          genres: place?.genres ?? [],
          lat: place?.lat ?? site.lat,
          lon: place?.lon ?? site.lon,
        }
      : null,
    area: size === null ? "" : String(size),
    kitchen: isKitchen(site.kitchen) ? site.kitchen : "unsure",
    outdoor: site.outdoor === true ? "yes" : site.outdoor === false ? "no" : "unsure",
  };
  return { site: { id: null, label: site.label, lat: site.lat, lon: site.lon }, form };
}
