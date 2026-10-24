/* The full-screen map's rules (map/SurveyMap.tsx, map/controller.ts): how close it frames a new site, what its card
   and the search boxes call the site, its control's words, and the history entry that lets Back leave it. */
import { reachM } from "../map/geometry";
import { asArea, type Area } from "./area";
import { coords } from "./format";

/** Street level: close enough to pick out one storefront. */
export const SITE_ZOOM = 16;
/** Still street level, one step out: where a walk too wide for the screen at 16 shows whole. */
export const STREET_ZOOM = 15;

/**
 * The zoom a new site is framed at on the full-screen map, given the zoom at which its whole walk fits the screen:
 * street level (16), or a step out when the walk would not fit there, as on a phone, where a 10-minute walk at 16 is
 * wider than the screen; never further out than 15.
 */
export function streetZoom(walkFits: number): number {
  return Math.min(SITE_ZOOM, Math.max(STREET_ZOOM, walkFits));
}

/**
 * How far the area may reach, in meters: the radius of the circle drawn when it cannot be traced (a walk of `minutes` ×
 * 80 m, a drive of `minutes` × 400 m, a road distance of `km` × 700 m). A bare number of minutes is a walk.
 */
export const walkReach = (area: Area | number): number => reachM(asArea(area));

/** The name a site placed by hand on the map takes in the brief. */
export const DROPPED_PIN = "Dropped pin";

/** What the full-screen map's card calls the site: its address, or its coordinates for a pin placed by hand. */
export function spotTitle(label: string | null | undefined, lat: number, lon: number): { text: string; isCoords: boolean } {
  const name = label?.trim();
  return name && name !== DROPPED_PIN ? { text: name, isCoords: false } : { text: coords(lat, lon), isCoords: true };
}

/**
 * What a search box says once a site is set, however it was set (SearchBox.tsx): the site's name, or nothing for a pin
 * placed by hand, which has no address to search for.
 */
export function searchText(label: string | null | undefined): string {
  const name = label?.trim();
  return name && name !== DROPPED_PIN ? name : "";
}

/** The corner control's name and tooltip, either way. */
export function expandLabel(expanded: boolean): string {
  return expanded ? "Exit full screen" : "Full-screen map";
}

/** The history entry the full-screen map adds, so the browser's Back shrinks it instead of leaving the page. */
export const FULL_MAP_ENTRY = { walkinFullMap: true } as const;

export function isFullMapEntry(state: unknown): boolean {
  return typeof state === "object" && state !== null && "walkinFullMap" in state && state.walkinFullMap === true;
}
