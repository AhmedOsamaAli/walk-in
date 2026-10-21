import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Walk, WalkMinutes } from "../api/types";
import { circleWalk } from "../map/geometry";

export interface Site {
  /** The preset's id, or null for a searched address or a dropped pin. */
  id: string | null;
  label: string;
  lat: number;
  lon: number;
}

const walkKey = (site: Site, minutes: number) => `${site.lat},${site.lon},${minutes}`;

/** The site's walking catchment over the street network, or an estimated circle when tracing fails; null while tracing. */
export function useSiteWalk(site: Site | null, minutes: WalkMinutes): Walk | null {
  const [traced, setTraced] = useState<{ key: string; walk: Walk } | null>(null);

  useEffect(() => {
    if (!site) return;
    const abort = new AbortController();
    const key = walkKey(site, minutes);
    void api
      .catchment(site.lat, site.lon, minutes, abort.signal)
      .catch(() => circleWalk(site.lat, site.lon, minutes))
      .then((walk) => {
        if (!abort.signal.aborted) setTraced({ key, walk });
      });
    return () => {
      abort.abort();
    };
  }, [site, minutes]);

  return site && traced?.key === walkKey(site, minutes) ? traced.walk : null;
}

export function walkNote(walk: Walk | null, minutes: WalkMinutes): string {
  if (!walk) return `Tracing a ${minutes}-min walk…`;
  const shape = walk.source === "circle" ? "estimated circle" : "street network";
  return `${walk.minutes}-min walk · ${walk.area_km2} km² · ${shape}`;
}
