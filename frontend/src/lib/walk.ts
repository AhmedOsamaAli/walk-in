/* A site's area as the brief and the map show it while it is traced (state/site.ts): the wait before tracing, what a
   failed trace shows, and the area in words. A bare number of minutes is a walk. */
import { ApiError } from "../api/client";
import type { Walk } from "../api/types";
import { circleWalk } from "../map/geometry";
import { areaNoun, areaShort, asArea, km2Text, walkShort, type Area } from "./area";

/** The walk: no site yet, being traced, traced (or estimated as a circle), or resting after too many map requests. */
export type WalkPreview = { phase: "none" } | { phase: "tracing" } | { phase: "shown"; walk: Walk } | { phase: "resting" };

export const NO_WALK: WalkPreview = { phase: "none" };
export const TRACING_WALK: WalkPreview = { phase: "tracing" };

/** A walk is traced once its site has stayed put this long, so a pin moved about sends one request, not one per tap. */
export const TRACE_DELAY_MS = 650;

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/**
 * An area that could not be traced. A 429 means the map requests are resting: the site stays and nothing is drawn.
 * Anything else draws the estimated circle, as the survey does when the street network cannot be read.
 */
export function failedWalk(error: unknown, spot: { lat: number; lon: number }, area: Area | number): WalkPreview {
  if (error instanceof ApiError && error.status === 429) return { phase: "resting" };
  return { phase: "shown", walk: circleWalk(spot.lat, spot.lon, area) };
}

/**
 * The area in words, under the chosen site: empty without one. Once traced, the area's own words from the server
 * ("30-min drive · 210 km² · street network"). `waking` says why tracing takes long.
 */
export function walkLine(preview: WalkPreview, area: Area | number, waking = false): string {
  const asked = asArea(area);
  switch (preview.phase) {
    case "none":
      return "";
    case "tracing":
      return waking
        ? `Tracing the ${areaShort(asked)}. The survey engine is waking up, which can take a minute.`
        : `Tracing a ${areaShort(asked)}…`;
    case "shown": {
      const { walk } = preview;
      const shape = walk.source === "circle" ? "estimated circle" : "street network";
      return `${walkShort(walk)} · ${km2Text(walk.area_km2)} km² · ${shape}`;
    }
    case "resting": {
      const noun = areaNoun(asked);
      return `The ${noun} preview is resting after many map requests. Your site stays, and the survey still traces the ${noun}.`;
    }
  }
}
