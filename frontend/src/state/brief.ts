import type { Focus, Intent, Kitchen, PlaceCard, PlaceHit, RunRequest, RunSite, WalkMinutes } from "../api/types";
import { FOCUS_LABELS, floorArea, isFocus, isIntent, isKitchen, KITCHEN_LABELS } from "../lib/format";
import type { Site } from "./site";

export type AreaUnit = "m2" | "ft2";
export type Choice = "yes" | "no" | "unsure";

/** Everything the owner sets in the brief before a survey. */
export interface BriefForm {
  intent: Intent;
  minutes: WalkMinutes;
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
  minutes: 10,
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

/** What still stops the survey from starting, as the button's hint; null when it can start. */
export function missing(site: Site | null, form: BriefForm): string | null {
  if (!site) return "Choose a site first.";
  if (form.intent === "open" && !form.business.trim()) return "Say what you want to open.";
  if (form.intent === "improve" && !form.place) return "Find your place on Qloo first.";
  if (form.intent !== "improve" && form.area.trim() && floorArea(form.area, form.areaUnit) === null) {
    return "The floor area must be between 10 and 2,000 m² (110–21,500 ft²).";
  }
  return null;
}

/** The survey the brief asks for. Improving a place compares the place itself, so unit details and notes stay out. */
export function runRequest(site: Site, form: BriefForm): RunRequest {
  const run: RunRequest = {
    lat: site.lat,
    lon: site.lon,
    label: site.label,
    focus: form.intent === "explore" ? form.focus : "any",
    notes: form.intent === "improve" ? "" : form.notes.trim(),
    minutes: form.minutes,
    intent: form.intent,
  };
  if (form.intent === "open") run.business = form.business.trim().slice(0, BUSINESS_MAX);
  if (form.intent === "improve" && form.place) run.placeId = form.place.id;
  if (form.intent !== "improve") {
    const size = floorArea(form.area, form.areaUnit);
    if (size !== null) run.sizeM2 = size;
    if (form.kitchen !== "unsure") run.kitchen = form.kitchen;
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

/** What the survey is about, for the title block's second field. */
export function askedLine(run: RunRequest, place: PlaceHit | null): { label: string; line: string } {
  if (run.intent === "open") return { label: "Your idea", line: run.business ?? "" };
  if (run.intent === "improve") {
    const genre = place?.genres?.[0];
    return { label: "Your place", line: [place?.name ?? run.label, genre].filter(Boolean).join(" · ") };
  }
  return { label: "Business", line: FOCUS_LABELS[run.focus] };
}

const isWalkMinutes = (value: unknown): value is WalkMinutes => value === 5 || value === 10 || value === 15;

/**
 * The site and brief a recorded survey was run with, as the server read them: its title block is rebuilt from them, and
 * a new survey can start from them. `place` is the owner's place the run found, when improving it.
 */
export function briefOf(site: RunSite, place: PlaceCard | null): { site: Site; form: BriefForm } {
  const intent = isIntent(site.intent) ? site.intent : "explore";
  const placeId = intent === "improve" && typeof site.place_id === "string" ? site.place_id : "";
  const size = typeof site.size_m2 === "number" && Number.isFinite(site.size_m2) ? site.size_m2 : null;
  const form: BriefForm = {
    ...initialBrief,
    intent,
    minutes: isWalkMinutes(site.minutes) ? site.minutes : initialBrief.minutes,
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
