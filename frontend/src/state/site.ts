import { useEffect, useEffectEvent, useState } from "react";
import { api } from "../api/client";
import type { ReverseResult } from "../api/types";
import { areaKey, asArea, type Area } from "../lib/area";
import { unnamed } from "../lib/fullmap";
import { failedWalk, isAbort, NO_WALK, TRACE_DELAY_MS, TRACING_WALK, type WalkPreview } from "../lib/walk";

export interface Site {
  /** The preset's id, or null for a searched address or a dropped pin. */
  id: string | null;
  /** The address, or DROPPED_PIN (lib/fullmap.ts) for a pin placed by hand until its address comes. */
  label: string;
  lat: number;
  lon: number;
}

interface Point {
  lat: number;
  lon: number;
}

/** The same spot on the map, whatever each is called. */
export function samePoint(a: Point | null | undefined, b: Point | null | undefined): boolean {
  if (!a || !b) return false;
  return a.lat === b.lat && a.lon === b.lon;
}

const traceKey = (site: Point, area: Area) => `${site.lat},${site.lon},${areaKey(area)}`;

/**
 * The site's area over the street network (a walk, a drive or a road distance; a bare number of minutes is a walk),
 * traced once the site and the area have stayed put a moment: being traced, traced (or an estimated circle when tracing
 * fails), or resting after too many map requests, which keeps the site and draws nothing. No area (a number out of the
 * limits typed in the brief) traces nothing. A site renamed where it stands (a dropped pin's address coming) is not
 * traced again.
 */
export function useSiteWalk(site: Site | null, asked: Area | number | null): WalkPreview {
  const [traced, setTraced] = useState<{ key: string; preview: WalkPreview } | null>(null);
  const area = asked === null ? null : asArea(asked);
  // The trace follows the site's spot and the area's values, not their objects, which each render or rename makes anew.
  const lat = site?.lat ?? null;
  const lon = site?.lon ?? null;
  const travel = area?.travel ?? null;
  const amount = area === null ? null : area.travel === "distance" ? area.km : area.minutes;

  useEffect(() => {
    if (lat === null || lon === null || travel === null || amount === null) return;
    const shape: Area = travel === "distance" ? { travel, km: amount } : { travel, minutes: amount };
    const spot = { lat, lon };
    const abort = new AbortController();
    const key = traceKey(spot, shape);
    const timer = window.setTimeout(() => {
      api.catchment(lat, lon, shape, abort.signal).then(
        (walk) => {
          if (!abort.signal.aborted) setTraced({ key, preview: { phase: "shown", walk } });
        },
        (error: unknown) => {
          if (!abort.signal.aborted && !isAbort(error)) setTraced({ key, preview: failedWalk(error, spot, shape) });
        },
      );
    }, TRACE_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [lat, lon, travel, amount]);

  if (!site || !area) return NO_WALK;
  return traced?.key === traceKey(site, area) ? traced.preview : TRACING_WALK;
}

/** A site to look up the address of: a pin placed by hand on the map, while its label names no place. */
export const awaitsAddress = (site: Site | null): site is Site => site !== null && site.id === null && unnamed(site.label);

/**
 * The pin with the address found for it, while it is still the pin that was looked up: not moved, replaced or named
 * since. Anything else is returned as it is.
 */
export function withAddress(site: Site | null, pin: Point, address: string): Site | null {
  return awaitsAddress(site) && samePoint(site, pin) ? { ...site, label: address } : site;
}

type Reverse = (lat: number, lon: number, signal?: AbortSignal) => Promise<ReverseResult>;

/**
 * A dropped pin's address from OpenStreetMap (GET /api/reverse): its short label ("131 South 2nd Street, Williamsburg,
 * Brooklyn"), or null when the point has none (404), the lookup fails (502, offline) or is called off. Never throws.
 */
export async function addressAt(pin: Point, signal: AbortSignal, reverse: Reverse = api.reverse): Promise<string | null> {
  try {
    const found: unknown = await reverse(pin.lat, pin.lon, signal);
    const label = typeof found === "object" && found !== null && "label" in found ? found.label : null;
    const text = typeof label === "string" ? label.trim() : "";
    return signal.aborted || unnamed(text) ? null : text;
  } catch {
    return null;
  }
}

/** A pin is looked up once it has stayed put this long, so a pin moved about asks once, not once per tap (lookups
 * share OpenStreetMap's one request a second with address search). */
export const ADDRESS_DELAY_MS = 800;

/**
 * Looks up the address of a pin placed by hand, and hands it over while the pin stays where it was: moving or
 * replacing it calls the lookup off. The site goes by its coordinates while it waits, and for good when no address
 * comes; nothing waits for it.
 */
export function usePinAddress(site: Site | null, onAddress: (pin: Point, address: string) => void): void {
  const found = useEffectEvent(onAddress);
  const waiting = awaitsAddress(site);
  const lat = site?.lat ?? null;
  const lon = site?.lon ?? null;

  useEffect(() => {
    if (!waiting || lat === null || lon === null) return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      void addressAt({ lat, lon }, abort.signal).then((address) => {
        if (address !== null && !abort.signal.aborted) found({ lat, lon }, address);
      });
    }, ADDRESS_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [waiting, lat, lon]);
}
