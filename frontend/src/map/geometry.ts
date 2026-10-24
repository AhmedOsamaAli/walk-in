import type { LatLon, Walk } from "../api/types";
import { areaLabel, areaShort, asArea, type Area } from "../lib/area";

const METERS_PER_DEGREE = 111_320;
export const WALK_M_PER_MIN = 80;
/** A drive's reach per minute when it cannot be traced: about 24 km/h, with the lights, the turns and the parking. */
export const DRIVE_M_PER_MIN = 400;
/** A road distance's reach per km when it cannot be traced: roads wind, so a km of road gets about 700 m away. */
export const ROAD_M_PER_KM = 700;

/** How far from the site the area reaches when it cannot be traced, in meters. The server draws the same circle. */
export function reachM(area: Area): number {
  if (area.travel === "distance") return area.km * ROAD_M_PER_KM;
  return area.minutes * (area.travel === "drive" ? DRIVE_M_PER_MIN : WALK_M_PER_MIN);
}

/** Wider than the widest walk Walk-in offered before drives (15 minutes): the brief says what such an area suits. */
export const isBigArea = (area: Area): boolean => reachM(area) > 15 * WALK_M_PER_MIN;

/**
 * A circle of the area's reach, used when the street network cannot be traced. A bare number of minutes is a walk. For a
 * road distance, `minutes` is the drive at DRIVE_M_PER_MIN; it is never shown.
 */
export function circleWalk(lat: number, lon: number, area: Area | number): Walk {
  const shape = asArea(area);
  const radius = reachM(shape);
  const dLat = radius / METERS_PER_DEGREE;
  const dLon = radius / (METERS_PER_DEGREE * Math.cos((lat * Math.PI) / 180));
  const ring = Array.from({ length: 41 }, (_, i): LatLon => {
    const angle = (2 * Math.PI * (i % 40)) / 40;
    return [lat + dLat * Math.sin(angle), lon + dLon * Math.cos(angle)];
  });
  return {
    minutes: shape.travel === "distance" ? Math.ceil(radius / DRIVE_M_PER_MIN) : shape.minutes,
    source: "circle",
    ring,
    area_km2: +(Math.PI * (radius / 1000) ** 2).toFixed(3),
    radius_m: radius,
    travel: shape.travel,
    km: shape.travel === "distance" ? shape.km : null,
    label: areaLabel(shape),
    short: areaShort(shape),
  };
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

/** Great-circle distance in meters between two [lat, lon] points. */
export function distanceM([lat1, lon1]: LatLon, [lat2, lon2]: LatLon): number {
  const rad = Math.PI / 180;
  const h =
    Math.sin(((lat2 - lat1) * rad) / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(((lon2 - lon1) * rad) / 2) ** 2;
  return 2 * 6_371_000 * Math.asin(Math.min(1, Math.sqrt(h)));
}
