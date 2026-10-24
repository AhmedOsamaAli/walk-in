/* How far customers come from (features/CONTRACT.md, "Area size"): a walk or a drive of so many minutes, or a road
   distance in km. The brief picks it, the preview and the survey trace it, and the map draws a circle of the same reach
   when it cannot be traced (map/geometry.ts). */
import type { Travel, Walk } from "../api/types";

export type Area = { travel: "walk" | "drive"; minutes: number } | { travel: "distance"; km: number };

/** The brief's area until the owner picks another, and the area of every survey made before drives and distances. */
export const WALK_10: Area = { travel: "walk", minutes: 10 };

/** The routing server's limits: 5 to 60 minutes of walking or driving, 1 to 100 km of road. */
export const MINUTES_MIN = 5;
export const MINUTES_MAX = 60;
export const KM_MIN = 1;
export const KM_MAX = 100;
export const MINUTE_PICKS: readonly number[] = [5, 10, 15, 30, 60];
export const KM_PICKS: readonly number[] = [5, 10, 25, 50, 100];

export const TRAVEL_LABELS: Record<Travel, string> = { walk: "Walk", drive: "Drive", distance: "Distance" };
export const isTravel = (value: unknown): value is Travel => typeof value === "string" && Object.hasOwn(TRAVEL_LABELS, value);

/** Minutes typed for a walk or a drive: a whole number from 5 to 60; null for anything else. */
export function parseMinutes(text: string): number | null {
  const value = text.trim();
  if (!/^\d{1,3}$/.test(value)) return null;
  const minutes = Number(value);
  return minutes >= MINUTES_MIN && minutes <= MINUTES_MAX ? minutes : null;
}

/** Kilometers typed for a road distance: 1 to 100 with one decimal at most ("2.5", "2,5"); null for anything else. */
export function parseKm(text: string): number | null {
  const value = text.trim().replace(",", ".");
  if (!/^\d{1,3}(\.\d?)?$/.test(value)) return null;
  const km = Number(value);
  return km >= KM_MIN && km <= KM_MAX ? km : null;
}

/** The area as the server words it inside a sentence: "10-minute walk", "30-minute drive", "25 km drive". */
export function areaLabel(area: Area): string {
  return area.travel === "distance" ? `${area.km} km drive` : `${area.minutes}-minute ${area.travel}`;
}

/** The area as chips and the map line name it: "10-min walk", "30-min drive", "25 km drive". */
export function areaShort(area: Area): string {
  return area.travel === "distance" ? `${area.km} km drive` : `${area.minutes}-min ${area.travel}`;
}

/** The noun for the area in a sentence: "the walk", "the drive" (a road distance is driven too). */
export const areaNoun = (area: Area): string => (area.travel === "walk" ? "walk" : "drive");

/** One string per area, for keys: "walk:10", "drive:30", "distance:25". */
export const areaKey = (area: Area): string =>
  area.travel === "distance" ? `distance:${area.km}` : `${area.travel}:${area.minutes}`;

/** A bare number of minutes is a walk, as everywhere before drives and distances. */
export const asArea = (area: Area | number): Area => (typeof area === "number" ? { travel: "walk", minutes: area } : area);

/**
 * The area a survey asked for, from what the server recorded or traced: one without `travel` is a walk; values out of
 * the limits fall back to the brief's 10-minute walk.
 */
export function areaOf(value: { travel?: unknown; minutes?: unknown; km?: unknown }): Area {
  const travel = isTravel(value.travel) ? value.travel : "walk";
  if (travel === "distance") {
    const km = typeof value.km === "number" ? parseKm(String(value.km)) : null;
    return km === null ? WALK_10 : { travel, km };
  }
  const minutes = typeof value.minutes === "number" ? parseMinutes(String(value.minutes)) : null;
  return minutes === null ? WALK_10 : { travel, minutes };
}

/** The traced area's own words when the server sent them ("30-min drive", else "30-minute drive"), else ours. */
export const walkShort = (walk: Walk): string => walk.short ?? walk.label ?? areaShort(areaOf(walk));

/** The traced area inside a sentence, in the server's words ("30-minute drive"); for an older survey, "10-minute walk". */
export const walkLabel = (walk: Walk): string => walk.label ?? areaLabel(areaOf(walk));

/** Square kilometers as the walk line says them: "0.503", "1.21", "15.3", "210", "1,924". */
export function km2Text(value: number): string {
  if (value >= 100) return Math.round(value).toLocaleString("en-US");
  if (value >= 10) return String(Math.round(value * 10) / 10);
  return String(value);
}
