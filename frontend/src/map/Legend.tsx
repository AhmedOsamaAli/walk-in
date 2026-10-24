import { useState } from "react";
import type { GapRow } from "../api/types";
import { PinMark } from "../components/PlaceCard";
import { AREA, gapPins, inSentence, insideLine, lovedInsideLine, osmLine, outsideLine } from "./pins";

/** Open by default where the map has room for it; a tap away on phones and tablets. */
const ROOMY = "(min-width: 981px)";

interface LegendProps {
  /** The area's outline as the legend names it: the server's "10-min walk", "30-min drive" or "25 km drive". */
  areaLabel: string;
  /** The area inside a sentence ("the walk"), for its counts. */
  area?: string;
  /** The open category, whose places the map labels; null while none is open. */
  gap?: GapRow | null;
  /** The open category's name, from callers that do not pass the category itself. */
  gapGenre?: string | null;
  /** How many places Qloo lists inside the area, said while no category is open. */
  placeCount?: number | null;
  /** The survey's categories have arrived, so one can be opened. */
  canOpen?: boolean;
  /** The open category's taste grid is on the map. */
  grid?: boolean;
}

/** What the map shows now, and how many of each: only the roles on it. */
export function Legend({
  areaLabel,
  area = AREA,
  gap = null,
  gapGenre = null,
  placeCount = null,
  canOpen = false,
  grid = true,
}: LegendProps) {
  const [open] = useState(() => window.matchMedia(ROOMY).matches);
  const pins = gap ? gapPins(gap).summary : null;
  const genre = gap?.genre ?? gapGenre;
  const lovedRole = pins?.kind === "citywide" ? "famous" : "loved";
  return (
    <details className="legend" open={open}>
      <summary className="mono">Legend</summary>
      <ul className="legend-list">
        <li>
          <i className="lg-site" />
          Site
        </li>
        <li>
          <i className="lg-ring" />
          {areaLabel}
        </li>
        {pins?.inside ? (
          <li>
            <PinMark mark="1" role="inside" />
            {insideLine(pins, area)}
          </li>
        ) : null}
        {pins?.osm ? (
          <li>
            <PinMark mark={String(pins.inside + 1)} role="osm" />
            {osmLine(pins)}
          </li>
        ) : null}
        {pins?.outside ? (
          <li>
            <PinMark mark="A" role={lovedRole} />
            {outsideLine(pins, area)}
          </li>
        ) : null}
        {pins?.lovedInside ? (
          <li>
            <PinMark mark="A" role={lovedRole} />
            {lovedInsideLine(pins, area)}
          </li>
        ) : null}
        {genre && grid ? (
          <li>
            <i className="lg-grid" />
            Taste for {inSentence(genre)} by area
          </li>
        ) : null}
        {!genre && placeCount ? (
          <li className="lg-note">
            Qloo lists {placeCount} {placeCount === 1 ? "place" : "places"} inside {area}.
            {canOpen ? " Open a category to see its places here." : ""}
          </li>
        ) : null}
        <li className="lg-source">Places and taste: Qloo</li>
      </ul>
    </details>
  );
}
