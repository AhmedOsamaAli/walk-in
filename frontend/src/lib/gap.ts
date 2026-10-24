import type { GapRow, OsmCheck, OsmPlace } from "../api/types";
import { gapWhy, safeLink } from "./format";

/** The badge of a gap whose fans travel for it. Surveys saved before the wording changed say "Locals travel for it". */
export const TRAVEL_READING = "People here travel for it";
const LEGACY_READINGS: Readonly<Record<string, string>> = { "Locals travel for it": TRAVEL_READING };

/** The server's badge as it reads today, older surveys' wording included. */
export function readingLabel(reading: string | null | undefined): string | null {
  if (!reading) return null;
  return LEGACY_READINGS[reading] ?? reading;
}

/** The badge's tone: a real gap is highlighted, a crowded or uncertain one is muted. */
export function readingTone(reading: string | null | undefined): "strong" | "weak" | "" {
  const label = readingLabel(reading);
  if (label === "Clear gap" || label === "Under-supplied" || label === TRAVEL_READING) return "strong";
  if (label === "Crowded" || label === "Thin data" || label === "Atypical") return "weak";
  return "";
}

/** The one evidence line that explains the badge; the rest are in the expanded row. */
export function leadLine(gap: GapRow): string {
  const why = gap.why ?? [];
  const find = (pattern: RegExp) => why.find((line) => pattern.test(line));
  switch (readingLabel(gap.reading)) {
    case TRAVEL_READING:
      return find(/outside the walk|already inside the walk/) ?? why[0] ?? gapWhy(gap);
    case "Clear gap":
    case "Under-supplied":
    case "Crowded":
      return find(/inside the \d+-minute walk/) ?? why[0] ?? gapWhy(gap);
    case "Thin data":
    case "Atypical":
      return why.at(-1) ?? gapWhy(gap);
    default:
      return why[0] ?? gapWhy(gap);
  }
}

/** OpenStreetMap's credit, shown wherever its places are (its data is under the Open Database License). */
export const OSM_CREDIT = "© OpenStreetMap contributors";
export const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
const OSM_HOST = "www.openstreetmap.org";

/** The places of the gap's kind only OpenStreetMap shows inside the walk, each with a location and its OpenStreetMap page. */
export function osmExtra(gap: GapRow): OsmPlace[] {
  return (gap.osm?.extra ?? []).filter(
    (place) =>
      typeof place.name === "string" &&
      place.name.trim() !== "" &&
      Number.isFinite(place.lat) &&
      Number.isFinite(place.lon) &&
      osmLink(place.url) !== null,
  );
}

/** A link to an OpenStreetMap page, or null for anything else. */
export function osmLink(url: unknown): string | null {
  const href = safeLink(url);
  return href && new URL(href).host === OSM_HOST ? href : null;
}

/** Places of the kind inside the walk, Qloo's and OpenStreetMap's extras: what the gap is scored on. */
export function supplyCount(gap: GapRow): number {
  return gap.nearby_count + osmExtra(gap).length;
}

/** Why a gap was not cross-checked, in words; null when it was, or for surveys saved before the cross-check existed. */
export function osmUnchecked(osm: OsmCheck | null | undefined): string | null {
  if (!osm || osm.checked) return null;
  if (osm.reason === "unmapped") return "Not cross-checked: no OpenStreetMap tag reliably marks this kind of place.";
  if (osm.reason === "unavailable") return "Not cross-checked: OpenStreetMap did not answer in time.";
  return "Not cross-checked with OpenStreetMap.";
}

/** What the cross-check found when every place it shows is one Qloo lists too, or why they were not compared. */
export function osmConfirmed(osm: OsmCheck | null | undefined): string | null {
  if (!osm?.checked || osm.extra.length) return null;
  if (osm.note) return osm.note;
  if (!osm.count) return "OpenStreetMap shows none inside the walk either.";
  return `OpenStreetMap shows ${osm.count} inside the walk, all on Qloo's list too.`;
}

/** "331 m away · shop=pastry" */
export function osmDetail(place: OsmPlace): string {
  return [place.distance_m != null ? `${place.distance_m} m away` : "", place.tag ?? ""].filter(Boolean).join(" · ");
}
