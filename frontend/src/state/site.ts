import { useEffect, useState } from "react";
import { api } from "../api/client";
import { areaKey, asArea, type Area } from "../lib/area";
import { failedWalk, isAbort, NO_WALK, TRACE_DELAY_MS, TRACING_WALK, type WalkPreview } from "../lib/walk";

export interface Site {
  /** The preset's id, or null for a searched address or a dropped pin. */
  id: string | null;
  label: string;
  lat: number;
  lon: number;
}

const traceKey = (site: Site, area: Area) => `${site.lat},${site.lon},${areaKey(area)}`;

/**
 * The site's area over the street network (a walk, a drive or a road distance; a bare number of minutes is a walk),
 * traced once the site and the area have stayed put a moment: being traced, traced (or an estimated circle when tracing
 * fails), or resting after too many map requests, which keeps the site and draws nothing. No area (a number out of the
 * limits typed in the brief) traces nothing.
 */
export function useSiteWalk(site: Site | null, asked: Area | number | null): WalkPreview {
  const [traced, setTraced] = useState<{ key: string; preview: WalkPreview } | null>(null);
  const area = asked === null ? null : asArea(asked);
  // The trace follows the area's values, not its object, which each render makes anew.
  const travel = area?.travel ?? null;
  const amount = area === null ? null : area.travel === "distance" ? area.km : area.minutes;

  useEffect(() => {
    if (!site || travel === null || amount === null) return;
    const shape: Area = travel === "distance" ? { travel, km: amount } : { travel, minutes: amount };
    const abort = new AbortController();
    const key = traceKey(site, shape);
    const timer = window.setTimeout(() => {
      api.catchment(site.lat, site.lon, shape, abort.signal).then(
        (walk) => {
          if (!abort.signal.aborted) setTraced({ key, preview: { phase: "shown", walk } });
        },
        (error: unknown) => {
          if (!abort.signal.aborted && !isAbort(error)) setTraced({ key, preview: failedWalk(error, site, shape) });
        },
      );
    }, TRACE_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
      abort.abort();
    };
  }, [site, travel, amount]);

  if (!site || !area) return NO_WALK;
  return traced?.key === traceKey(site, area) ? traced.preview : TRACING_WALK;
}
