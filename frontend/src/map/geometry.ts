import type { LatLon, Walk } from "../api/types";

const METERS_PER_DEGREE = 111_320;
export const WALK_M_PER_MIN = 80;

/** A circle of the distance walked in `minutes`, used when the street network cannot be traced. */
export function circleWalk(lat: number, lon: number, minutes: number): Walk {
  const radius = minutes * WALK_M_PER_MIN;
  const dLat = radius / METERS_PER_DEGREE;
  const dLon = radius / (METERS_PER_DEGREE * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: 41 }, (_, i): LatLon => {
    const angle = (2 * Math.PI * (i % 40)) / 40;
    return [lat + dLat * Math.sin(angle), lon + dLon * Math.cos(angle)];
  });
  return { minutes, source: "circle", ring, area_km2: +(Math.PI * (radius / 1000) ** 2).toFixed(3), radius_m: radius };
}

/** A quadratic curve from one point to another, bowed to one side so overlapping trips stay apart. */
export function arc(from: LatLon, to: LatLon, steps = 40): LatLon[] {
  const [fromLat, fromLon] = from;
  const [toLat, toLon] = to;
  const dx = toLon - fromLon;
  const dy = toLat - fromLat;
  const cx = (fromLon + toLon) / 2 - dy * 0.2;
  const cy = (fromLat + toLat) / 2 + dx * 0.2;
  return Array.from({ length: steps + 1 }, (_, i): LatLon => {
    const t = i / steps;
    const u = 1 - t;
    return [u * u * fromLat + 2 * u * t * cy + t * t * toLat, u * u * fromLon + 2 * u * t * cx + t * t * toLon];
  });
}

/** The size of a geohash cell in degrees, as [lat, lon]. */
export function cellSpan(geohash: string | null): [number, number] {
  const bits = 5 * ((geohash ?? "").length || 7);
  return [180 / 2 ** Math.floor(bits / 2), 360 / 2 ** Math.ceil(bits / 2)];
}

/** Degrees of latitude spanned by a distance in meters. */
export const metersToLat = (meters: number) => meters / METERS_PER_DEGREE;
